"""Build the circuit once, then only switch things between runs (Team Nando Tutorial 4 approach).

A BaseCircuit compiles the network one time and adds, before the first solve:
  - one load shape per randomly profiled customer (its demand is overwritten for every scenario);
  - the fixed load shapes found by topology.fixed_load_shapes() (e.g. commercial loads);
  - one PV system per candidate customer (disabled, resized and switched on per scenario), all
    following one shared PV shape;
  - one curve + InvControl per inverter control mode (volt-watt, volt-var), all disabled; the
    scenario's mode is switched on. Creating every control before the first solve avoids the
    OpenDSS crash seen when an InvControl is added to a solved circuit.
Each simulate(scenario) then edits only what changed since the previous scenario, resets the
controls, solves the day and records results with vectorised reads (all node voltages and all
asset loadings in one call per time step).

simulate() returns the same dictionary as hosting.simulate(), plus all-asset loading:
asset_pct_max (highest % of rating of every monitored transformer and line over the window) and
assets (the topology.Asset of each). Load P and Q are the demand given to OpenDSS (constant-power
loads draw exactly that between their vminpu and vmaxpu); fixed-shape loads are read back.
Check it against a full rebuild with verify_base_circuit() before relying on a new network.
"""
import numpy as np

from . import der as der_text, engine as eng, extract, network as net, timeseries as ts

PV_SHAPE = "toolkit_pv_shape"


class BaseCircuit:
    def __init__(self, engine, setup, info, pv_candidates, inverter_controls=None, n_steps=48, step_minutes=30):
        """setup: hosting.StudySetup; info: topology.read_network() of the same setup;
        pv_candidates: customers that may get PV; inverter_controls: {"volt_watt": InverterControl, ...}."""
        self.engine, self.setup, self.info = engine, setup, info
        self.n_steps, self.step_minutes = n_steps, step_minutes
        self.random_customers = info.random_customers
        self.pv_candidates = list(pv_candidates)
        self.controls = dict(inverter_controls or {})
        eng.build_circuit(engine, setup.circuit_source, setup.voltage_bases_kv, bus_coordinates=setup.bus_coordinates)
        zeros = np.zeros(n_steps)
        commands = []
        for load, (shape, how) in info.fixed_loads.items():
            if how != "linked in circuit":
                commands.append(f"edit Load.{load} daily={shape}")
        self.demand_shape = {}
        for i, customer in enumerate(self.random_customers):
            name = f"toolkit_demand_{i}"
            self.demand_shape[customer] = name
            commands += [der_text.loadshape_command(name, zeros, zeros, step_minutes, use_actual=True),
                         f"edit Load.{customer} daily={name}"]
        commands.append(der_text.loadshape_command(PV_SHAPE, zeros, interval_minutes=step_minutes, use_actual=False))
        for customer in self.pv_candidates:
            load = info.loads[customer]
            commands.append(der_text.pv_command(f"pv_{customer}", load["bus"], len(net.bus_phases(load["bus"])), load["kV"],
                                                1.0, 1.0, daily_shape=PV_SHAPE, kvar_max=1.0, extra="enabled=no"))
        for mode, control in self.controls.items():
            curve = f"toolkit_{mode}_curve"
            commands += [der_text.xy_curve_command(curve, control.voltage_pu, control.output_pu),
                         der_text.inverter_control_command(f"toolkit_{mode}", mode, curve, extra="enabled=no")]
        eng.run_commands(engine, commands)
        eng.set_daily_mode(engine, step_minutes)
        eng.solve(engine, verbose=False)               # initialise every element once before the first scenario
        self.taps = _transformer_taps(engine)
        self.pv_state = {c: None for c in self.pv_candidates}
        self.pv_index = {}
        pv = engine.ActiveCircuit.PVSystems
        for k in range(pv.Count):
            pv.idx = k + 1
            self.pv_index[pv.Name.lower()] = k + 1
        self._demand_id = self._pv_profile = self._connections = None
        self._control = "unset"
        self._pv_version, self._control_der = 0, None
        self.loads = net.element_names(engine.ActiveCircuit.Loads)
        self.fixed_load_list = [l for l in self.loads if l in info.fixed_loads]
        self.asset_positions = extract.asset_positions(engine, info.assets)
        self.assets = self.asset_positions[0]
        head = [a.element for a in self.assets if a.kind == "head_transformer"]
        self.transformer = setup.transformer or (head[0].split(".", 1)[1] if head else
                                                 net.element_names(engine.ActiveCircuit.Transformers)[0])
        self._index_load_nodes()

    # --- bookkeeping -----------------------------------------------------------------------
    def _index_load_nodes(self):
        """Positions in AllBusVmagPu of every node each load is connected to (redone after a phase change)."""
        nodes = {n.lower(): i for i, n in enumerate(self.engine.ActiveCircuit.AllNodeNames)}
        flat, starts = [], []
        for load in self.loads:
            bus_text = net.element_bus(self.engine, f"Load.{load}").lower()
            bus = net.bus_name(bus_text)
            starts.append(len(flat))
            flat += [nodes[f"{bus}.{p}"] for p in sorted(net.bus_phases(bus_text)) if f"{bus}.{p}" in nodes]
        self.node_flat, self.node_starts = np.array(flat, dtype=int), np.array(starts, dtype=int)

    def _set_demand(self, demand):
        shapes = self.engine.ActiveCircuit.LoadShapes
        for customer, (p, q) in demand.items():
            shapes.Name = self.demand_shape[customer]
            shapes.Pmult = np.asarray(p, dtype=float)
            shapes.Qmult = np.asarray(q, dtype=float)

    def _set_connections(self, connections):
        """Apply a phase assignment ({element: bus text}), restoring elements not in it."""
        wanted = dict(self.info_default_connections())
        wanted.update(connections or {})
        commands = [f"edit {element} bus1={bus}" for element, bus in wanted.items()]
        eng.run_commands(self.engine, commands)
        self._index_load_nodes()

    def info_default_connections(self):
        """Original bus of every element a phase assignment may change (tap points and their PV)."""
        if not hasattr(self, "_default_connections"):
            defaults = {}
            for customer, tap in self.info.tap_points.items():
                defaults[tap.element] = tap.bus_text
                if tap.element.startswith("load.") and customer in self.pv_state:
                    defaults[f"pvsystem.pv_{customer}"] = tap.bus_text
            self._default_connections = defaults
        return self._default_connections

    def _set_pv(self, der):
        wanted = {d.customer: (d.kva, d.pmpp or d.kva) for d in der if d.kind == "pv"}
        unknown = set(wanted) - set(self.pv_state)
        if unknown:
            raise KeyError(f"PV for customers that are not PV candidates of this BaseCircuit: {sorted(unknown)[:3]}")
        commands = []
        for customer, state in self.pv_state.items():
            target = wanted.get(customer)
            if target != state:
                if target is None:
                    commands.append(f"edit PVSystem.pv_{customer} enabled=no")
                else:
                    kva, pmpp = target
                    commands.append(f"edit PVSystem.pv_{customer} kVA={kva:.6g} Pmpp={pmpp:.6g} "
                                    f"kvarMax={kva:.6g} kvarMaxAbs={kva:.6g} enabled=yes")
                self.pv_state[customer] = target
        if commands:
            self._pv_version += 1
        eng.run_commands(self.engine, commands)

    def _set_control(self, control):
        mode = control.mode if control is not None else None
        if control is not None:
            if mode not in self.controls:
                raise KeyError(f"no '{mode}' InvControl in this BaseCircuit (give it in inverter_controls)")
            base = self.controls[mode]
            if (tuple(base.voltage_pu), tuple(base.output_pu)) != (tuple(control.voltage_pu), tuple(control.output_pu)):
                eng.run_commands(self.engine, [der_text.xy_curve_command(f"toolkit_{mode}_curve", control.voltage_pu,
                                                                          control.output_pu).replace("new ", "edit ", 1)])
                self.controls[mode] = control
        circuit = self.engine.ActiveCircuit
        enabled_pv = sorted(c for c, state in self.pv_state.items() if state is not None)
        if mode is not None and enabled_pv and (mode, tuple(enabled_pv), self._pv_version) != self._control_der:
            # an InvControl keeps the ratings of its PV from when it read them: give it the current list
            der_list = " ".join(f"PVSystem.pv_{c}" for c in enabled_pv)
            eng.run_commands(self.engine, [f"edit InvControl.toolkit_{mode} DERList=[{der_list}]"])
            self._control_der = (mode, tuple(enabled_pv), self._pv_version)
        for m in self.controls:
            circuit.SetActiveElement(f"InvControl.toolkit_{m}")
            circuit.ActiveCktElement.Enabled = (m == mode and bool(enabled_pv))
        # a control leaves its last setpoints in the PV systems: put every PV back to unity power
        # factor and full output whenever the control mode changes
        if mode != self._control:
            eng.run_commands(self.engine, [f"edit PVSystem.pv_{c} pf=1 %Pmpp=100" for c in self.pv_candidates])
            self._control = mode

    # --- one scenario -----------------------------------------------------------------------
    def apply(self, scenario):
        """Edit the circuit to match a scenario (only what changed since the previous one)."""
        connections = getattr(scenario, "connections", None) or {}
        if connections != self._connections:
            self._set_connections(connections)
            self._connections = connections
        if id(scenario.demand) != self._demand_id:
            self._set_demand(scenario.demand)
            self._demand_id = id(scenario.demand)
        self._set_pv(scenario.der)
        pv = [d for d in scenario.der if d.kind == "pv"]
        if pv:
            profile = np.asarray(pv[0].profile, dtype=float)
            if any(not np.array_equal(d.profile, profile) for d in pv[1:]):
                raise ValueError("BaseCircuit needs every PV of a scenario to follow the same profile")
            if self._pv_profile is None or not np.array_equal(profile, self._pv_profile):
                shapes = self.engine.ActiveCircuit.LoadShapes
                shapes.Name = PV_SHAPE
                shapes.Pmult = profile
                self._pv_profile = profile
        self._set_control(scenario.inverter_control)

    def simulate(self, scenario):
        """Run one scenario over its window; same result dictionary as hosting.simulate(), plus
        asset_pct_max / assets for every monitored transformer and line."""
        engine, circuit = self.engine, self.engine.ActiveCircuit
        self.apply(scenario)
        _restore_taps(engine, self.taps)
        eng.run_commands(engine, ["Reset"])
        eng.set_daily_mode(engine, scenario.window.step_minutes)
        eng.solve(engine, verbose=False)                  # warm-up step: lets every element take up its new
        eng.set_daily_mode(engine, scenario.window.step_minutes)   # shape values, then restart at hour 0
        n = scenario.window.n_steps
        pv_customers = [d.customer for d in scenario.der if d.kind == "pv"]
        pv_idx = [self.pv_index[f"pv_{c}".lower()] for c in pv_customers]
        v_min = np.zeros((len(self.loads), n))
        tx_p, tx_q, der_p, der_q = [], [], np.zeros((n, len(pv_idx))), np.zeros((n, len(pv_idx)))
        fixed_pq = np.zeros((2, len(self.fixed_load_list), n))
        asset_max = np.zeros(len(self.assets))
        pvs = circuit.PVSystems
        converged = True
        for step in range(n):
            converged &= eng.solve(engine, verbose=False)
            v = np.asarray(circuit.AllBusVmagPu)[self.node_flat]
            v_min[:, step] = np.minimum.reduceat(v, self.node_starts) if len(v) else v
            if len(self.assets):
                np.maximum(asset_max, extract.asset_loading(engine, self.asset_positions), out=asset_max)
            p, q, _, _ = _transformer_flow(engine, self.transformer)
            tx_p.append(p)
            tx_q.append(q)
            for j, k in enumerate(pv_idx):
                pvs.idx = k                                   # also makes it the active circuit element
                powers = circuit.ActiveCktElement.Powers
                der_p[step, j], der_q[step, j] = -sum(powers[0::2]), -sum(powers[1::2])
            for j, load in enumerate(self.fixed_load_list):
                lp, lq = extract.element_powers(engine, f"Load.{load}")
                fixed_pq[:, j, step] = lp.sum(), lq.sum()
        p_all, q_all = np.zeros((len(self.loads), n)), np.zeros((len(self.loads), n))
        row = {l: i for i, l in enumerate(self.loads)}
        for customer, (p, q) in scenario.demand.items():
            p_all[row[customer]], q_all[row[customer]] = p, q
        for j, load in enumerate(self.fixed_load_list):
            p_all[row[load]], q_all[row[load]] = fixed_pq[0, j], fixed_pq[1, j]
        circuit.Transformers.Name = self.transformer
        available = np.array([d.available_power_kw for d in scenario.der]).T if scenario.der else np.zeros((n, 0))
        return {"scenario": scenario, "loads": self.loads, "der": [f"PVSystem.pv_{c}" for c in pv_customers],
                "converged": converged, "transformer": self.transformer,
                "transformer_kva": self.setup.transformer_rating_kva or circuit.Transformers.kVA,
                "P": p_all, "Q": q_all, "V": v_min, "tx_P": np.array(tx_p), "tx_Q": np.array(tx_q),
                "der_P": der_p, "der_Q": der_q, "der_available_P": available,
                "asset_pct_max": asset_max, "assets": self.assets}


def _transformer_flow(engine, name):
    """(P per phase, Q per phase, ...) out of winding 2 of one transformer (as extract.transformer_results)."""
    p, q = extract.element_powers(engine, f"Transformer.{name}", terminal=1)
    n_phases = engine.ActiveCircuit.ActiveCktElement.NumPhases
    return -p[:n_phases], -q[:n_phases], None, None


def _transformer_taps(engine):
    tr = engine.ActiveCircuit.Transformers
    taps = {}
    i = tr.First
    while i:
        taps[tr.Name] = []
        for w in range(1, tr.NumWindings + 1):
            tr.Wdg = w
            taps[tr.Name].append(tr.Tap)
        i = tr.Next
    return taps


def _restore_taps(engine, taps):
    tr = engine.ActiveCircuit.Transformers
    for name, values in taps.items():
        tr.Name = name
        for w, tap in enumerate(values, start=1):
            tr.Wdg = w
            tr.Tap = tap
