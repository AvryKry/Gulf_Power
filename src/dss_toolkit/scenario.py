"""Scenarios: an explicit record of what is simulated.

A Scenario says, for one time window, which demand every customer has and which DER (PV, and later
batteries, EVs ...) sits behind which customer, with what size and profile. It holds plain data only:
building one needs no OpenDSS, and the same scenario can be simulated, saved, reloaded and audited.

Builders turn profile data into scenarios (random_scenario, penetration_scenarios); anything else
(measured smart-meter data, a hand-made case) can build a Scenario directly.
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
    def label(self):
        """'day 21', 'days 21-27', or 'steps 1010-1100' for a window that is not whole days."""
        whole = self.start_step % self.steps_per_day == 0 and self.n_steps % self.steps_per_day == 0
        if not whole:
            return f"steps {self.start_step}-{self.start_step + self.n_steps - 1}"
        n_days = self.n_steps // self.steps_per_day
        return f"day {self.first_day}" if n_days == 1 else f"days {self.first_day}-{self.first_day + n_days - 1}"


# --- DER -----------------------------------------------------------------------------------------
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


# --- Scenario ------------------------------------------------------------------------------------
@dataclass
class Scenario:
    """window: TimeWindow; demand: {customer: (P [kW], Q [kvar]) arrays over the window};
    der: list of DER; tags: free labels copied into every result row (penetration, seed, season ...)."""
    window: TimeWindow
    demand: dict
    der: list
    tags: dict = field(default_factory=dict)

    @property
    def customers(self):
        return list(self.demand)

    def with_pv_profile(self, profile, **tags):
        """The same scenario with every PV following 'profile' (and extra tags, e.g. pv_profile=2)."""
        der = [replace(d, profile=np.asarray(profile)) if d.kind == "pv" else d for d in self.der]
        return replace(self, der=der, tags={**self.tags, **tags})

    def with_tags(self, **tags):
        return replace(self, tags={**self.tags, **tags})


# --- Builders (no OpenDSS needed) -----------------------------------------------------------------
def sample_demand(customers, load_data, window, rng, pf_range):
    """Give every customer a random profile from 'load_data' (profiles, days, steps) [kW] over the
    window, and Q from a random power factor per step. Returns ({customer: (P, Q)}, {customer: index})."""
    pool = ts.profiles_in_window(load_data, window)
    demand, index = {}, {}
    for c in customers:
        i = int(rng.integers(pool.shape[0]))
        p = pool[i]
        demand[c] = (p, ts.reactive_power(p, ts.random_power_factors(rng, len(p), pf_range)))
        index[c] = i
    return demand, index


def pv_fleet(customers, profile, kva, pmpp=None):
    """A PV system of the same size and profile behind each of 'customers'."""
    return [DER("pv", c, kva, np.asarray(profile), pmpp) for c in customers]


def random_scenario(customers, load_data, pv_data, window, penetration_pct, seed=10,
                    pf_range=(0.9, 0.98), pv_kva=10.0, pv_pmpp=None):
    """Random demand for every customer and PV on 'penetration_pct' % of them.
    The demand depends only on (seed, first day of the window), and the PV customers only on 'seed',
    so a higher penetration keeps the same demand and only adds PV. pv_data = (days, steps) or one
    profile covering the window."""
    rng = np.random.default_rng([seed, window.first_day])
    demand, index = sample_demand(customers, load_data, window, rng, pf_range)
    pv = np.asarray(pv_data)
    profile = ts.profiles_in_window(pv, window) if pv.ndim == 2 else pv
    with_pv = ts.pv_customers(ts.customer_order(customers, seed), penetration_pct)
    return Scenario(window, demand, pv_fleet(with_pv, profile, pv_kva, pv_pmpp),
                    {"window": window.label, "penetration": penetration_pct, "seed": seed,
                     "n_pv": len(with_pv), "profile_index": index})


def penetration_scenarios(customers, load_data, pv_data, window, penetrations, **options):
    """One random_scenario per penetration (same demand, nested PV customers)."""
    return [random_scenario(customers, load_data, pv_data, window, p, **options) for p in penetrations]


# --- Saving and loading --------------------------------------------------------------------------
def save_scenario(scenario, path):
    """Save a scenario to a .npz file (arrays) with its window, DER list and tags as JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays = {f"P__{c}": p for c, (p, q) in scenario.demand.items()}
    arrays.update({f"Q__{c}": q for c, (p, q) in scenario.demand.items()})
    arrays.update({f"DER__{i}": d.profile for i, d in enumerate(scenario.der)})
    meta = {"window": [scenario.window.start_step, scenario.window.n_steps, scenario.window.step_minutes],
            "customers": scenario.customers, "tags": scenario.tags,
            "der": [{"kind": d.kind, "customer": d.customer, "kva": d.kva, "pmpp": d.pmpp} for d in scenario.der]}
    np.savez_compressed(path, meta=json.dumps(meta, default=str), **arrays)


def load_scenario(path):
    """Read a scenario saved with save_scenario()."""
    with np.load(path, allow_pickle=False) as f:
        meta = json.loads(str(f["meta"]))
        demand = {c: (f[f"P__{c}"], f[f"Q__{c}"]) for c in meta["customers"]}
        der = [DER(d["kind"], d["customer"], d["kva"], f[f"DER__{i}"], d["pmpp"]) for i, d in enumerate(meta["der"])]
    return Scenario(TimeWindow(*meta["window"]), demand, der, meta["tags"])
