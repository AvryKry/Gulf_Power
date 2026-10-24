"""Storing study results: one table row per simulation (pandas), and full simulations on disk.

Long studies append each row to a CSV file as they go, so nothing is lost if a run stops, and
full time series can be saved per run instead of being kept in memory.
Results contain network data: keep the results folder in .gitignore.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd


def to_table(rows):
    """List of summary dicts -> pandas DataFrame (one row per simulation)."""
    return pd.DataFrame(list(rows))


def append_row(path, row):
    """Append one summary dict to a CSV file (header written when the file is new)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([row]).to_csv(path, mode="a", header=not path.exists(), index=False)


def load_table(path):
    """Read a results CSV written by append_row() / run_study()."""
    return pd.read_csv(path)


SIM_ARRAYS = ("P", "Q", "V", "tx_P", "tx_Q", "der_P", "der_Q")


def save_simulation(sim, path):
    """Save the time series of one simulation (P, Q, V, transformer and DER arrays) to a .npz file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {k: sim[k] for k in ("loads", "der", "transformer", "transformer_kva", "converged")}
    meta["tags"] = sim["scenario"].tags
    np.savez_compressed(path, meta=json.dumps(meta, default=str), **{k: sim[k] for k in SIM_ARRAYS})


def load_simulation(path):
    """Read a simulation saved with save_simulation() (without its scenario object)."""
    with np.load(path, allow_pickle=False) as f:
        sim = json.loads(str(f["meta"]))
        sim.update({k: f[k] for k in SIM_ARRAYS})
    return sim
