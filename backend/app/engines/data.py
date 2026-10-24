"""Loads the processed challenge data once and exposes fast lookups for the engines."""
from functools import cached_property, lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROCESSED = ROOT / "data" / "processed"
WEATHER = PROCESSED / "weather"
DOCS = ROOT / "docs"
WORKBOOK = ROOT / "data" / "Install_Labor_HackOHIO.xlsx"


class GridData:
    """Premises, devices, topology chains, assets, damage records and grid cells."""

    def __init__(self):
        self.prem: pd.DataFrame = pd.read_pickle(PROCESSED / "premises.pkl")
        self.dev: pd.DataFrame = pd.read_pickle(PROCESSED / "devices.pkl")
        chains = pd.read_pickle(PROCESSED / "chains.pkl")
        self.chain_p = chains.p.to_numpy()
        self.chain_d = chains.d.to_numpy()
        self.chain_hop = chains.hop.to_numpy()
        self.assets: pd.DataFrame = pd.read_pickle(PROCESSED / "assets.pkl")
        self.damage: pd.DataFrame = pd.read_pickle(PROCESSED / "damage.pkl")
        self.cells: pd.DataFrame = pd.read_pickle(PROCESSED / "cells.pkl")
        self.n_prem = len(self.prem)
        self.n_dev = len(self.dev)
        self.prem_customers = self.prem.customers.to_numpy()
        self.prem_index = {p: i for i, p in enumerate(self.prem.premise)}
        self.dev_customers = self.dev.customers.to_numpy()
        # premise -> cell row index (for weather lookups)
        self.cell_ids = self.cells.index.to_numpy()
        cell_pos = {c: i for i, c in enumerate(self.cell_ids)}
        self.prem_cell = np.array([cell_pos[c] for c in self.prem.cell])
        self.asset_cell = np.array([cell_pos.get(c, -1) for c in self.assets.cell])
        # assets grouped by cell and type, for damage sampling
        self.assets_by_cell_type: dict[tuple[int, str], np.ndarray] = {
            (cell_pos.get(c, -1), t): g.index.to_numpy()
            for (c, t), g in self.assets.groupby(["cell", "asset_type"])
        }
        # life-support premises behind each device (for priority + escalation)
        ls = self.prem.life_support.to_numpy()
        self.dev_life_support = np.bincount(self.chain_d, weights=ls[self.chain_p].astype(float),
                                            minlength=self.n_dev).astype(int)

    # ---- outage propagation through the topology
    def premises_out(self, damaged_devs: np.ndarray) -> np.ndarray:
        """Boolean mask of premises downstream of any damaged device."""
        dmask = np.zeros(self.n_dev, bool)
        dmask[damaged_devs[damaged_devs >= 0]] = True
        out = np.zeros(self.n_prem, bool)
        out[self.chain_p[dmask[self.chain_d]]] = True
        return out

    def restore_times(self, dev_time: np.ndarray) -> np.ndarray:
        """Per-premise restore time = latest restore time among devices in its chain (0 = never out)."""
        t = np.zeros(self.n_prem)
        np.maximum.at(t, self.chain_p, dev_time[self.chain_d])
        return t

    def chain_of(self, premise_idx: int) -> pd.DataFrame:
        rows = np.where(self.chain_p == premise_idx)[0]
        order = rows[np.argsort(self.chain_hop[rows])]
        return self.dev.iloc[self.chain_d[order]].assign(hop=self.chain_hop[order])

    @cached_property
    def zip_customers(self) -> pd.Series:
        return self.prem.groupby("zip").customers.sum()

    @cached_property
    def circuit_customers(self) -> pd.Series:
        return self.prem.groupby("circuit").customers.sum()


@lru_cache(maxsize=1)
def grid() -> GridData:
    return GridData()
