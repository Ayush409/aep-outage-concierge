"""Shared paths and helpers for the data-prep scripts."""
from pathlib import Path

import numpy as np
import shapefile

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
EXTRACTED = ROOT / "data" / "extracted"
PROCESSED = ROOT / "data" / "processed"
PROCESSED.mkdir(parents=True, exist_ok=True)

# Service-area bounding box (from Customer_Clip), padded slightly.
BBOX = (-80.26, 36.99, -79.64, 37.49)  # lon_min, lat_min, lon_max, lat_max
LAT0 = 37.24  # reference latitude for local planar distances


def layer(name: str) -> shapefile.Reader:
    """Open a shapefile by base name from extracted/ or raw/ (Data1 or Data2)."""
    for base in (EXTRACTED, RAW):
        for sub in ("Data1", "Data2"):
            p = base / sub / f"{name}.shp"
            if p.exists():
                return shapefile.Reader(str(p))
    raise FileNotFoundError(name)


def to_xy(lon, lat):
    """Lon/lat (deg) -> local planar metres, good enough for nearest-neighbour work."""
    lon = np.asarray(lon, dtype=float)
    lat = np.asarray(lat, dtype=float)
    x = (lon + 80.0) * 111_320.0 * np.cos(np.radians(LAT0))
    y = (lat - LAT0) * 110_540.0
    return np.column_stack([x, y])


CELL = 0.02  # grid cell size in degrees (~1.8 km x 2.2 km)


def cell_id(lon, lat):
    ix = np.floor((np.asarray(lon) - BBOX[0]) / CELL).astype(int)
    iy = np.floor((np.asarray(lat) - BBOX[1]) / CELL).astype(int)
    return iy * 1000 + ix


def cell_center(cid):
    cid = np.asarray(cid)
    iy, ix = cid // 1000, cid % 1000
    return BBOX[0] + (ix + 0.5) * CELL, BBOX[1] + (iy + 0.5) * CELL
