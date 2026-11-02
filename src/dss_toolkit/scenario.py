"""Scenarios: an explicit record of what is simulated.

A Scenario says, for one time window, which demand every customer has, which DER (PV, and later
batteries, EVs ...) sits behind which customer, with what size and profile, and which inverter
control (if any) the PV inverters use. It holds plain data only: building one needs no OpenDSS,
and the same scenario can be simulated, saved, reloaded and audited.

Every random choice has its own seed, so each source of randomness can be changed on its own:
    pv_placement_seed   which customers get PV (random PV build)
    load_profile_seed   which of the measured load profiles each customer gets
    power_factor_seed   the power factor of each customer at each step (gives kvar from kW)
    load_day_seed       which day of the load data is used (when it is not matched to the PV day)

Builders:
    random_scenario / penetration_scenarios   one window, PV on a % of customers (Tutorial 2)
    StudyPlan + plan_scenarios                ranked PV days x PV modes x penetrations (Tutorial 3)
Anything else (measured smart-meter data, a hand-made case) can build a Scenario directly.
"""
import json
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

from . import timeseries as ts


# --- Time window -------------------------------------------------------------------------------
@dataclass(frozen=True)
class TimeWindow:
    """A run of time steps counted from the start of the profile data (step 0 = day 0, 00:00)."""
    start_step: int
    n_steps: int
    step_minutes: int = 30

    @classmethod
    def days(cls, first_day, n_days=1, steps_per_day=48, step_minutes=30):
        """Whole days, e.g. TimeWindow.days(21) or TimeWindow.days(0, n_days=7)."""
        return cls(first_day * steps_per_day, n_days * steps_per_day, step_minutes)

    @property
    def steps_per_day(self):
        return 24 * 60 // self.step_minutes

    @property
    def first_day(self):
        return self.start_step // self.steps_per_day

    @property
    def hours_per_step(self):
        return self.step_minutes / 60

    @property
    def label(self):
        """'day 21', 'days 21-27', or 'steps 1010-1100' for a window that is not whole days."""
        whole = self.start_step % self.steps_per_day == 0 and self.n_steps % self.steps_per_day == 0
        if not whole:
            return f"steps {self.start_step}-{self.start_step + self.n_steps - 1}"
        n_days = self.n_steps // self.steps_per_day
        return f"day {self.first_day}" if n_days == 1 else f"days {self.first_day}-{self.first_day + n_days - 1}"


# --- DER and inverter control --------------------------------------------------------------------
@dataclass(frozen=True)
class DER:
    """One DER behind one customer. kind = "pv" today; new kinds only need a command builder in
    timeseries.DER_BUILDERS. 'profile' is normalised (0-1) over the scenario's window."""
    kind: str
    customer: str
    kva: float
    profile: np.ndarray = field(repr=False)
    pmpp: float = None

    @property
    def name(self):
        return f"{self.kind}_{self.customer}"

    @property
    def available_power_kw(self):
        """Power the DER could deliver at each step without curtailment [kW]: the profile times
        Pmpp, capped by the inverter rating."""
        return np.minimum(np.asarray(self.profile) * (self.pmpp or self.kva), self.kva)


@dataclass(frozen=True)
class InverterControl:
    """A volt-watt or volt-var curve used by every PV inverter of a scenario.
    mode: "volt_watt" or "volt_var"; voltage_pu: x points of the curve [pu of rated voltage];
    output_pu: y points - active power limit [pu of Pmpp] for volt-watt, reactive power
    [pu of the inverter kVA, + = injected] for volt-var; source: where the settings come from."""
    mode: str
    voltage_pu: tuple
    output_pu: tuple
    source: str = ""


# PV operation modes: what each one puts in a scenario
PV_MODES = {"no_pv": "No PV", "pv": "PV, no control", "pv_volt_watt": "PV + volt-watt", "pv_volt_var": "PV + volt-var"}
PV_MODE_CONTROL = {"no_pv": None, "pv": None, "pv_volt_watt": "volt_watt", "pv_volt_var": "volt_var"}


# --- Scenario ------------------------------------------------------------------------------------
@dataclass
class Scenario:
    """window: TimeWindow; demand: {customer: (P [kW], Q [kvar]) arrays over the window};
    der: list of DER; tags: labels copied into every result row (penetration, seeds, day ...);
    inverter_control: InverterControl used by every PV inverter, or None."""
    window: TimeWindow
    demand: dict
    der: list
    tags: dict = field(default_factory=dict)
    inverter_control: InverterControl = None

    @property
    def customers(self):
        return list(self.demand)

    def with_pv_profile(self, profile, **tags):
        """The same scenario with every PV following 'profile' (and extra tags, e.g. pv_profile=2)."""
        der = [replace(d, profile=np.asarray(profile)) if d.kind == "pv" else d for d in self.der]
        return replace(self, der=der, tags={**self.tags, **tags})

    def with_tags(self, **tags):
        return replace(self, tags={**self.tags, **tags})

    def with_pv_mode(self, pv_mode, inverter_controls=None):
        """The same scenario run in a PV mode (see PV_MODES): "no_pv" removes the PV, "pv" keeps
        it without control, "pv_volt_watt" / "pv_volt_var" add the matching curve from
        'inverter_controls' = {"volt_watt": InverterControl, "volt_var": InverterControl}."""
        if pv_mode not in PV_MODES:
            raise ValueError(f"pv_mode must be one of {list(PV_MODES)}, not {pv_mode!r}")
        control_mode = PV_MODE_CONTROL[pv_mode]
        control = (inverter_controls or {}).get(control_mode) if control_mode else None
        if control_mode and control is None:
            raise ValueError(f"PV mode '{pv_mode}' needs inverter_controls['{control_mode}']")
        der = [] if pv_mode == "no_pv" else self.der
        return replace(self, der=der, inverter_control=control, tags={**self.tags, "pv_mode": pv_mode})


# --- PV days (no OpenDSS needed) -------------------------------------------------------------------
def rank_pv_days(pv_profiles_pu):
    """Day indices of 'pv_profiles_pu' (days, steps) from the highest daily peak to the lowest
    (rank 0 = worst case for over-voltage). Equal peaks are ordered by daily energy."""
    profiles = np.asarray(pv_profiles_pu)
    return np.lexsort((-profiles.sum(axis=1), -profiles.max(axis=1)))


def sample_ranked_days(ranked_days, rank_interval, include_best_day=True):
    """[(rank, day)] for every 'rank_interval'-th rank, from rank 0 (worst), plus the last rank
    (best day, lowest peak) if 'include_best_day'."""
    ranks = list(range(0, len(ranked_days), rank_interval))
    if include_best_day and ranks[-1] != len(ranked_days) - 1:
        ranks.append(len(ranked_days) - 1)
    return [(rank, int(ranked_days[rank])) for rank in ranks]


def choose_load_days(pv_days, use_matched_load_day, n_load_days, load_day_seed):
    """The load data day used with each PV day: the same day when 'use_matched_load_day', otherwise
    a random day (one draw per PV day, from 'load_day_seed' only)."""
    if use_matched_load_day:
        return [int(d) for d in pv_days]
    rng = np.random.default_rng(load_day_seed)
    return [int(d) for d in rng.integers(n_load_days, size=len(pv_days))]


# --- Demand (no OpenDSS needed) ----------------------------------------------------------------------
def assign_load_profiles(customers, n_profiles, load_profile_seed):
    """{customer: index of the measured load profile it uses}, from 'load_profile_seed' only. The
    same customer keeps the same profile on every simulated day."""
    rng = np.random.default_rng(load_profile_seed)
    return {c: int(i) for c, i in zip(customers, rng.integers(n_profiles, size=len(customers)))}


def build_demand(profile_index_by_customer, load_profiles_kw, load_window, power_factor_seed,
                 power_factor_range=(0.9, 0.98)):
    """{customer: (P [kW], Q [kvar])} over 'load_window' of the load data (profiles, days, steps).
    Q comes from a random power factor per customer and step within 'power_factor_range', drawn
    from 'power_factor_seed' and the load day only (not from which profile a customer has)."""
    profiles_in_window = ts.profiles_in_window(load_profiles_kw, load_window)
    rng = np.random.default_rng([power_factor_seed, load_window.first_day])
    demand = {}
    for customer, index in profile_index_by_customer.items():
        p_kw = profiles_in_window[index]
        power_factors = ts.random_power_factors(rng, len(p_kw), power_factor_range)
        demand[customer] = (p_kw, ts.reactive_power(p_kw, power_factors))
    return demand


# --- PV fleets (no OpenDSS needed) ---------------------------------------------------------------------
def pv_fleet(customers, profile, kva, pmpp=None):
    """A PV system of the same size and profile behind each of 'customers'."""
    return [DER("pv", c, kva, np.asarray(profile), pmpp) for c in customers]


def pv_fleet_from_sites(pv_sites, profile, customers=None):
    """PV systems from a list of site dicts {"customer": load name, "kva": rating, "pmpp": optional},
    all following 'profile'. With 'customers' (the circuit's load names), site names are matched
    ignoring upper/lower case (OpenDSS stores names in lower case) and unknown names are refused."""
    names = {c.lower(): c for c in customers} if customers is not None else None
    fleet = []
    for site in pv_sites:
        customer = site["customer"]
        if names is not None:
            if customer.lower() not in names:
                raise KeyError(f"PV site customer '{customer}' is not a load of the circuit, e.g. {list(names.values())[:3]}")
            customer = names[customer.lower()]
        fleet.append(DER("pv", customer, site["kva"], np.asarray(profile), site.get("pmpp")))
    return fleet


def random_pv_customers(customers, penetration_pct, pv_placement_seed):
    """The customers with PV for a penetration [% of customers]. A higher penetration keeps the
    customers that already have PV (same 'pv_placement_seed' = same order)."""
    return ts.pv_customers(ts.customer_order(customers, pv_placement_seed), penetration_pct)


# --- Tutorial 2 builders -------------------------------------------------------------------------------
def random_scenario(customers, load_profiles_kw, pv_profiles_pu, window, penetration_pct, pv_placement_seed=10,
                    load_profile_seed=10, power_factor_seed=10, power_factor_range=(0.9, 0.98), pv_kva=10.0,
                    pv_pmpp=None):
    """Random demand for every customer (load data day = the window's day) and PV on
    'penetration_pct' % of them. pv_profiles_pu = (days, steps) or one profile covering the window."""
    profile_index = assign_load_profiles(customers, load_profiles_kw.shape[0], load_profile_seed)
    demand = build_demand(profile_index, load_profiles_kw, window, power_factor_seed, power_factor_range)
    pv = np.asarray(pv_profiles_pu)
    profile = ts.profiles_in_window(pv, window) if pv.ndim == 2 else pv
    with_pv = random_pv_customers(customers, penetration_pct, pv_placement_seed)
    return Scenario(window, demand, pv_fleet(with_pv, profile, pv_kva, pv_pmpp),
                    {"window": window.label, "penetration_pct": penetration_pct, "n_pv_systems": len(with_pv),
                     "pv_placement_seed": pv_placement_seed, "load_profile_seed": load_profile_seed,
                     "power_factor_seed": power_factor_seed})


def penetration_scenarios(customers, load_profiles_kw, pv_profiles_pu, window, penetrations_pct, **options):
    """One random_scenario per penetration (same demand, nested PV customers)."""
    return [random_scenario(customers, load_profiles_kw, pv_profiles_pu, window, p, **options)
            for p in penetrations_pct]


# --- Tutorial 3: a study plan made of user selections ----------------------------------------------------
@dataclass
class StudyPlan:
    """Every selection of a ranked-day PV study, in the order a user would make them.
    pv_build: "random" (PV on a % of customers) or "sites" (the 'pv_sites' list).
    penetration_run: "single" (first value of penetrations_pct) or "sweep" (every value); random only.
    pv_modes: any of PV_MODES; inverter_controls: {"volt_watt": InverterControl, "volt_var": ...}.
    rank_interval / include_best_day: which ranked PV days are simulated (see sample_ranked_days)."""
    circuit_name: str
    pv_build: str
    pv_modes: tuple
    pv_rating_kva: float = 10.0
    pv_placement_seed: int = 1
    pv_sites: list = field(default_factory=list)
    penetration_run: str = "single"
    penetrations_pct: tuple = (100,)
    inverter_controls: dict = field(default_factory=dict)
    rank_interval: int = 25
    include_best_day: bool = True
    use_matched_load_day: bool = True
    load_day_seed: int = 1
    load_profile_seed: int = 1
    power_factor_seed: int = 1
    power_factor_range: tuple = (0.9, 0.98)

    def __post_init__(self):
        if self.pv_build not in ("random", "sites"):
            raise ValueError(f"pv_build must be 'random' or 'sites', not {self.pv_build!r}")
        if self.penetration_run not in ("single", "sweep"):
            raise ValueError(f"penetration_run must be 'single' or 'sweep', not {self.penetration_run!r}")
        if not self.pv_modes or any(m not in PV_MODES for m in self.pv_modes):
            raise ValueError(f"pv_modes must be 1 to 4 of {list(PV_MODES)}, not {self.pv_modes!r}")
        if self.pv_build == "sites" and not self.pv_sites:
            raise ValueError("pv_build='sites' needs at least one entry in pv_sites")

    @property
    def is_sweep(self):
        return self.pv_build == "random" and self.penetration_run == "sweep"

    @property
    def penetrations_to_run(self):
        """Penetrations simulated for the PV modes ([None] for a site list)."""
        if self.pv_build == "sites":
            return [None]
        return list(self.penetrations_pct) if self.is_sweep else [self.penetrations_pct[0]]

    def penetrations_for(self, pv_mode):
        """Penetrations simulated in one PV mode: "no_pv" runs once (0 %, or None for a site list)."""
        if pv_mode == "no_pv":
            return [0] if self.pv_build == "random" else [None]
        return self.penetrations_to_run

    @property
    def load_day_selection(self):
        return "matched" if self.use_matched_load_day else "independent"


def plan_pv_fleet(plan, customers, pv_profile, penetration_pct):
    """The PV fleet of a plan for one penetration (random build) or its site list."""
    if plan.pv_build == "sites":
        return pv_fleet_from_sites(plan.pv_sites, pv_profile, customers)
    return pv_fleet(random_pv_customers(customers, penetration_pct, plan.pv_placement_seed), pv_profile,
                    plan.pv_rating_kva)


def plan_scenarios(plan, customers, load_profiles_kw, pv_profiles_pu, steps_per_day=48, step_minutes=30):
    """Every scenario of a StudyPlan: for each sampled PV day (worst to best), each PV mode and
    each penetration. "no_pv" runs once per day. Returns (scenarios, [(rank, pv_day)])."""
    sampled_days = sample_ranked_days(rank_pv_days(pv_profiles_pu), plan.rank_interval, plan.include_best_day)
    load_days = choose_load_days([day for _, day in sampled_days], plan.use_matched_load_day,
                                 load_profiles_kw.shape[1], plan.load_day_seed)
    profile_index = assign_load_profiles(customers, load_profiles_kw.shape[0], plan.load_profile_seed)
    scenarios = []
    for (rank, pv_day), load_day in zip(sampled_days, load_days):
        pv_window = TimeWindow.days(pv_day, steps_per_day=steps_per_day, step_minutes=step_minutes)
        load_window = TimeWindow.days(load_day, steps_per_day=steps_per_day, step_minutes=step_minutes)
        pv_profile = ts.profiles_in_window(pv_profiles_pu, pv_window)
        demand = build_demand(profile_index, load_profiles_kw, load_window, plan.power_factor_seed,
                              plan.power_factor_range)
        for pv_mode in plan.pv_modes:
            for penetration_pct in plan.penetrations_for(pv_mode):
                fleet = [] if pv_mode == "no_pv" else plan_pv_fleet(plan, customers, pv_profile, penetration_pct)
                tags = {"circuit": plan.circuit_name, "pv_build": plan.pv_build, "pv_mode": pv_mode,
                        "penetration_pct": penetration_pct, "n_pv_systems": len(fleet),
                        "pv_total_kva": sum(d.kva for d in fleet), "pv_rank": rank, "pv_day": pv_day,
                        "pv_peak_pu": float(pv_profile.max()), "load_day_selection": plan.load_day_selection,
                        "load_day": load_day, "window": pv_window.label,
                        "pv_placement_seed": plan.pv_placement_seed if plan.pv_build == "random" else None,
                        "load_profile_seed": plan.load_profile_seed, "power_factor_seed": plan.power_factor_seed,
                        "load_day_seed": None if plan.use_matched_load_day else plan.load_day_seed}
                scenario = Scenario(pv_window, demand, fleet, tags)
                scenarios.append(scenario.with_pv_mode(pv_mode, plan.inverter_controls))
    return scenarios, sampled_days


# --- Saving and loading --------------------------------------------------------------------------
def save_scenario(scenario, path):
    """Save a scenario to a .npz file (arrays) with its window, DER list, control and tags as JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays = {f"P__{c}": p for c, (p, q) in scenario.demand.items()}
    arrays.update({f"Q__{c}": q for c, (p, q) in scenario.demand.items()})
    arrays.update({f"DER__{i}": d.profile for i, d in enumerate(scenario.der)})
    control = scenario.inverter_control
    meta = {"window": [scenario.window.start_step, scenario.window.n_steps, scenario.window.step_minutes],
            "customers": scenario.customers, "tags": scenario.tags,
            "der": [{"kind": d.kind, "customer": d.customer, "kva": d.kva, "pmpp": d.pmpp} for d in scenario.der],
            "inverter_control": None if control is None else
            {"mode": control.mode, "voltage_pu": list(control.voltage_pu), "output_pu": list(control.output_pu),
             "source": control.source}}
    np.savez_compressed(path, meta=json.dumps(meta, default=str), **arrays)


def load_scenario(path):
    """Read a scenario saved with save_scenario()."""
    with np.load(path, allow_pickle=False) as f:
        meta = json.loads(str(f["meta"]))
        demand = {c: (f[f"P__{c}"], f[f"Q__{c}"]) for c in meta["customers"]}
        der = [DER(d["kind"], d["customer"], d["kva"], f[f"DER__{i}"], d["pmpp"]) for i, d in enumerate(meta["der"])]
    control = meta.get("inverter_control")
    control = None if control is None else InverterControl(control["mode"], tuple(control["voltage_pu"]),
                                                           tuple(control["output_pu"]), control["source"])
    return Scenario(TimeWindow(*meta["window"]), demand, der, meta["tags"], control)
