"""Phase 1 data prep.

Reads the challenge shapefiles, topology file and damage records, and writes
analysis-ready tables to data/processed/:

  premises.pkl        one row per premise (location, circuit, OH/UG, customers, life support, zip)
  devices.pkl         transformers / fuses / reclosers / breakers with downstream counts
  chains.pkl          premise -> upstream device chain (index arrays)
  assets.pkl          poles, primary + secondary spans, transformers, fuses, reclosers, switches,
                      each with the protective device that isolates it and pole structure info
  damage.pkl          ARCOS damage records snapped to an asset + isolating device, tagged by event
  cells.pkl           0.02 deg grid cells with exposure features
  facilities.json     hospitals / fire / EMS (AEP-only)
  zcta.geojson        ZIP code tabulation areas covering the service area

Run:  .venv/Scripts/python scripts/prep_data.py
"""
import json
import math
import re
import sys
from collections import Counter, defaultdict

import httpx
import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy.spatial import cKDTree
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from common import BBOX, PROCESSED, ROOT, cell_center, cell_id, layer, to_xy  # noqa: E402


def log(*a):
    print("[prep]", *a, flush=True)


# ---------------------------------------------------------------- premises
def load_premises():
    r = layer("Customer_Clip")
    rows = []
    for sr in r.iterShapeRecords():
        d = sr.record.as_dict()
        x, y = sr.shape.points[0]
        rows.append(
            dict(
                premise=d["premise_nu"],
                lon=x,
                lat=y,
                circuit=d["circuit_id"],
                overhead=d["kind_of_se"] == "Overhead",
                service_kind=d["kind_of_se"],
                customers=max(int(d["customer_c"] or 1), 1),
                life_support=d["critical_c"].startswith("LS"),
                xfmr_loc=d["aep_xfmr_l"],
                city=d["city"],
                road=d["road_name"],
            )
        )
    df = pd.DataFrame(rows)
    df["cell"] = cell_id(df.lon, df.lat)
    log("premises", len(df), "customers", int(df.customers.sum()))
    return df


# ---------------------------------------------------------------- topology
KIND = {
    "Distribution": "transformer",
    "Step": "step",
    "Fuse": "fuse",
    "Recloser (Hydraulic)": "recloser",
    "Recloser (Electronic)": "recloser",
    "Sectionalizer": "sectionalizer",
    "Circuit Breaker": "breaker",
}


def load_topology(prem):
    path = None
    for p in (ROOT / "data/extracted/matched_upstream/matched_upstream.txt",
              ROOT / "data/raw/matched_upstream/matched_upstream.txt"):
        if p.exists():
            path = p
    if path is None:
        import zipfile
        z = zipfile.ZipFile(ROOT / "data/raw/matched_upstream.zip")
        lines = z.read("matched_upstream.txt").decode().splitlines()
    else:
        lines = path.read_text().splitlines()

    pidx = {p: i for i, p in enumerate(prem.premise)}
    dev_index, dev_rows = {}, []
    chain_p, chain_d, chain_h = [], [], []
    for line in lines:
        parts = line.rstrip("\n").split("\t")
        i = pidx.get(parts[0])
        if i is None:
            continue
        for hop, ent in enumerate(parts[1:]):
            _src, _id, devtype, loc = ent.split("*")
            kind = KIND.get(devtype, "other")
            key = f"{kind}:{loc}"
            j = dev_index.get(key)
            if j is None:
                j = dev_index[key] = len(dev_rows)
                dev_rows.append(dict(key=key, kind=kind, devtype=devtype, loc=loc))
            chain_p.append(i)
            chain_d.append(j)
            chain_h.append(hop)
    dev = pd.DataFrame(dev_rows)
    chains = pd.DataFrame(dict(p=chain_p, d=chain_d, hop=chain_h))
    # downstream premise and customer counts
    cust = prem.customers.to_numpy()
    dev["premises"] = np.bincount(chains.d, minlength=len(dev))
    dev["customers"] = np.bincount(chains.d, weights=cust[chains.p], minlength=len(dev)).astype(int)
    log("devices", len(dev), dict(Counter(dev.kind)), "chain rows", len(chains),
        "premises with chain", chains.p.nunique())
    return dev, chains


# ---------------------------------------------------------------- assets
def parse_kva(*specs):
    total = 0.0
    for s in specs:
        m = re.match(r"\s*([\d.]+)\s*kVA", s or "")
        if m:
            total += float(m.group(1))
    return total


def year_of(d):
    return d.year if hasattr(d, "year") else np.nan


def height_ft(s):
    m = re.match(r"(\d+)", s or "")
    return float(m.group(1)) if m else np.nan


def points_layer(name, fields):
    r = layer(name)
    rows = []
    for sr in r.iterShapeRecords():
        d = sr.record.as_dict()
        x, y = sr.shape.points[0]
        row = dict(lon=x, lat=y)
        for f in fields:
            row[f] = d.get(f)
        rows.append(row)
    return pd.DataFrame(rows)


def lines_layer(name, fields):
    r = layer(name)
    rows, verts, vseg = [], [], []
    for k, sr in enumerate(r.iterShapeRecords()):
        d = sr.record.as_dict()
        pts = np.asarray(sr.shape.points)
        mid = pts[len(pts) // 2] if len(pts) > 2 else pts.mean(axis=0)
        xy = to_xy(pts[:, 0], pts[:, 1])
        length = float(np.sum(np.hypot(*np.diff(xy, axis=0).T))) if len(pts) > 1 else 0.0
        row = dict(lon=mid[0], lat=mid[1], length_m=length,
                   x0=pts[0, 0], y0=pts[0, 1], x1=pts[-1, 0], y1=pts[-1, 1])
        for f in fields:
            row[f] = d.get(f)
        rows.append(row)
        verts.append(pts)
        vseg.append(np.full(len(pts), k))
    return pd.DataFrame(rows), np.vstack(verts), np.concatenate(vseg)


def build_assets(prem, dev, chains):
    log("reading layers ...")
    poles = points_layer("Pole_Clip", ["usage", "owner_name", "date_insta", "material", "height", "class"])
    poles = poles[poles.usage == "Pole"].reset_index(drop=True)
    poles["install_year"] = poles.date_insta.map(year_of)
    poles["height_ft"] = poles.height.map(height_ft)
    poles["shared"] = ~poles.owner_name.fillna("").str.startswith("APPALACHIAN")

    prim, pverts, pvseg = lines_layer(
        "Primary_ExportFeatures",
        ["usage", "esri_defau", "aep_constr", "nominal_vo", "existing_p", "circuit_id"])
    prim["phases"] = prim.esri_defau.str.extract(r"(\d) Phase")[0].astype(float).fillna(1).astype(int)
    sec, sverts, svseg = lines_layer("Secondary_ExportFeatures", ["circuit_id"])

    xf = points_layer("Transformer_Clip", ["location_n", "a_phase_sp", "b_phase_sp", "c_phase_sp",
                                           "existing_p", "mounting", "circuit_id", "a_phase_da"])
    xf["kva"] = [parse_kva(a, b, c) for a, b, c in zip(xf.a_phase_sp, xf.b_phase_sp, xf.c_phase_sp)]
    xf["install_year"] = xf.a_phase_da.map(year_of)
    fu = points_layer("Fuse_Bank_Clip", ["location_n", "circuit_id", "mounting", "aep_custom"])
    rc = points_layer("Recloser_Bank_Clip", ["location_n", "circuit_id", "device_typ", "aep_custom"])
    sw = points_layer("Switch_Clip", ["location_n", "circuit_id", "mounting"])

    # device coordinates from the point layers, else centroid of downstream premises
    coord = {}
    for df, kind in ((xf, "transformer"), (fu, "fuse"), (rc, "recloser")):
        for loc, lon, lat in zip(df.location_n, df.lon, df.lat):
            coord[f"{kind}:{loc}"] = (lon, lat)
    plon = np.bincount(chains.d, weights=prem.lon.to_numpy()[chains.p], minlength=len(dev))
    plat = np.bincount(chains.d, weights=prem.lat.to_numpy()[chains.p], minlength=len(dev))
    n = np.maximum(dev.premises.to_numpy(), 1)
    dev["lon"] = [coord.get(k, (plon[i] / n[i], plat[i] / n[i]))[0] for i, k in enumerate(dev.key)]
    dev["lat"] = [coord.get(k, (plon[i] / n[i], plat[i] / n[i]))[1] for i, k in enumerate(dev.key)]
    dev["has_gis_point"] = dev.key.isin(coord)

    # transformer -> upstream chain of protective devices (from any premise it serves)
    first = chains.sort_values(["p", "hop"])
    by_p = first.groupby("p").d.apply(list)
    xchain = {}
    for lst in by_p:
        if lst and lst[0] not in xchain:
            xchain[lst[0]] = lst[1:]
    kinds = dev.kind.to_numpy()

    def protector(chain_list, backbone):
        want = ("recloser", "breaker") if backbone else ("fuse", "recloser", "sectionalizer", "breaker")
        for j in chain_list:
            if kinds[j] in want:
                return j
        return chain_list[-1] if chain_list else -1

    # transformers in GIS -> device index
    dkey = {k: i for i, k in enumerate(dev.key)}
    xf["dev"] = [dkey.get(f"transformer:{loc}", -1) for loc in xf.location_n]
    xf_with_chain = xf[xf.dev.isin(list(xchain))].reset_index(drop=True)
    xtree = cKDTree(to_xy(xf_with_chain.lon, xf_with_chain.lat))

    def iso_for(lon, lat, backbone):
        _, k = xtree.query(to_xy(lon, lat))
        out = np.empty(len(k), dtype=int)
        for n_, kk in enumerate(k):
            d = int(xf_with_chain.dev.iloc[kk])
            out[n_] = protector(xchain[d], bool(backbone[n_]))
        return out, xf_with_chain.dev.to_numpy()[k]

    # primary: isolating device = lateral fuse or backbone recloser/breaker
    prim["backbone"] = prim.usage.eq("Backbone")
    prim["iso_dev"], prim["near_xfmr"] = iso_for(prim.lon, prim.lat, prim.backbone.to_numpy())
    # secondary: nearest transformer itself
    _, k = xtree.query(to_xy(sec.lon, sec.lat))
    sec["iso_dev"] = xf_with_chain.dev.to_numpy()[k]
    # transformers: themselves (if in topology) else nearest
    xf["iso_dev"] = xf.dev
    miss = xf.dev < 0
    if miss.any():
        _, k = xtree.query(to_xy(xf.lon[miss], xf.lat[miss]))
        xf.loc[miss, "iso_dev"] = xf_with_chain.dev.to_numpy()[k]
    xf["customers"] = [int(dev.customers.iloc[d]) if d >= 0 else 0 for d in xf.iso_dev]
    # fuses / reclosers: themselves if in topology, else nearest transformer's protector
    for df, kind, bb in ((fu, "fuse", False), (rc, "recloser", True)):
        df["dev"] = [dkey.get(f"{kind}:{loc}", -1) for loc in df.location_n]
        alt, _ = iso_for(df.lon, df.lat, np.full(len(df), bb))
        df["iso_dev"] = np.where(df.dev >= 0, df.dev, alt)
    sw["iso_dev"], _ = iso_for(sw.lon, sw.lat, np.ones(len(sw), bool))

    # ---- pole structure classification against the primary network
    log("classifying pole structures ...")
    pole_xy = to_xy(poles.lon, poles.lat)
    vtree = cKDTree(to_xy(pverts[:, 0], pverts[:, 1]))
    dist, vi = vtree.query(pole_xy, distance_upper_bound=15.0)
    has_prim = np.isfinite(dist)
    seg = np.where(has_prim, pvseg[np.minimum(vi, len(pvseg) - 1)], -1)
    ends = np.vstack([to_xy(prim.x0, prim.y0), to_xy(prim.x1, prim.y1)])
    end_seg = np.concatenate([np.arange(len(prim)), np.arange(len(prim))])
    end_other = np.vstack([to_xy(prim.x1, prim.y1), to_xy(prim.x0, prim.y0)])
    etree = cKDTree(ends)
    near_ends = etree.query_ball_point(pole_xy, r=4.0)
    degree, angle = np.zeros(len(poles), int), np.zeros(len(poles))
    for i, lst in enumerate(near_ends):
        segs = {}
        for e in lst:
            segs.setdefault(end_seg[e], e)
        degree[i] = len(segs)
        if len(segs) == 2:
            a, b = list(segs.values())
            v1 = end_other[a] - pole_xy[i]
            v2 = end_other[b] - pole_xy[i]
            cosang = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-9)
            angle[i] = 180.0 - math.degrees(math.acos(max(-1.0, min(1.0, cosang))))
    xd, xk = cKDTree(to_xy(xf.lon, xf.lat)).query(pole_xy, distance_upper_bound=8.0)
    has_xf = np.isfinite(xd)
    xk = np.minimum(xk, len(xf) - 1)

    def seg_attr(col, default):
        vals = prim[col].to_numpy()
        return np.where(seg >= 0, vals[np.maximum(seg, 0)], default)

    poles["primary_seg"] = seg
    poles["phases"] = seg_attr("phases", 0).astype(int)
    poles["crossarm"] = seg_attr("aep_constr", "") == "TC Typical CrossArm"
    poles["kv35"] = np.char.startswith(seg_attr("nominal_vo", "").astype(str), "34")
    poles["backbone"] = seg_attr("backbone", False).astype(bool)
    poles["degree"] = degree
    poles["angle"] = angle
    poles["xfmr_kva"] = np.where(has_xf, xf.kva.to_numpy()[xk], 0.0)
    poles["xfmr_phases"] = np.where(has_xf, xf.existing_p.fillna("").str.len().to_numpy()[xk], 0)

    def structure(r):
        three = r.phases >= 3
        if r.phases == 0:
            return "secondary", 0
        if r.xfmr_kva > 0:
            return ("transformer_bank", 1) if r.xfmr_phases >= 3 else ("transformer", 2)
        if r.degree == 1:
            return ("deadend_3ph", 8) if three else ("deadend_1ph", 3)
        if r.degree >= 3 or (r.degree == 2 and r.angle > 20):
            if three:
                return ("tap_3ph_crossarm", 6) if r.crossarm else ("tap_3ph_pin", 7)
            return ("angle_tap_1ph", 4)
        return ("tangent_3ph", 9) if three else ("tangent_1ph", 5)

    st = poles.apply(structure, axis=1, result_type="expand")
    poles["structure"], poles["drawing_page"] = st[0], st[1]
    poles["size_group"] = pd.cut(poles.height_ft.fillna(40), [0, 37, 57, 999],
                                 labels=["small", "medium", "large"]).astype(str)
    poles["iso_dev"] = -1
    on = poles.primary_seg >= 0
    poles.loc[on, "iso_dev"] = prim.iso_dev.to_numpy()[poles.primary_seg[on]]
    off = ~on
    _, k = xtree.query(pole_xy[off.to_numpy()])
    poles.loc[off, "iso_dev"] = xf_with_chain.dev.to_numpy()[k]
    log("pole structures", dict(Counter(poles.structure)))

    # unified asset table
    parts = []

    def add(df, atype, extra):
        a = pd.DataFrame(dict(asset_type=atype, lon=df.lon, lat=df.lat, iso_dev=df.iso_dev.astype(int)))
        for c in extra:
            a[c] = df[c].to_numpy()
        parts.append(a)

    add(poles, "pole", ["structure", "drawing_page", "size_group", "height_ft", "material", "install_year",
                        "phases", "crossarm", "kv35", "backbone", "xfmr_kva", "shared"])
    add(prim, "primary", ["length_m", "phases", "backbone", "aep_constr"])
    add(sec, "secondary", ["length_m"])
    add(xf, "transformer", ["kva", "install_year", "mounting", "customers"])
    add(fu, "fuse", [])
    add(rc, "recloser", [])
    add(sw, "switch", [])
    assets = pd.concat(parts, ignore_index=True)
    assets["cell"] = cell_id(assets.lon, assets.lat)
    log("assets", dict(Counter(assets.asset_type)))
    return assets


# ---------------------------------------------------------------- damage
ARCOS_TO_ASSET = {"Pole": "pole", "primary": "primary", "secondary": "secondary", "Fuse Bank": "fuse",
                  "Transformer": "transformer", "Recloser Bank": "recloser", "Switch": "switch",
                  "Capacitor Bank": "primary", "Step Transformer": "transformer", "Light": "secondary",
                  "(blank)": "primary"}


def build_damage(assets):
    src = PROCESSED / "damage_records.csv"
    if not src.exists():
        raise SystemExit("run scripts/export_damage.py first (writes damage_records.csv)")
    dmg = pd.read_csv(src)
    dmg["asset_type"] = dmg.asset_type.map(ARCOS_TO_ASSET).fillna("primary")
    dmg["asset"] = -1
    dmg["snap_m"] = np.nan
    for atype, g in dmg.groupby("asset_type"):
        cand = assets.index[assets.asset_type == atype]
        tree = cKDTree(to_xy(assets.lon[cand], assets.lat[cand]))
        d, k = tree.query(to_xy(g.longitude, g.latitude))
        dmg.loc[g.index, "asset"] = cand[k]
        dmg.loc[g.index, "snap_m"] = d
    dmg["iso_dev"] = assets.iso_dev.to_numpy()[dmg.asset]
    dmg["cell"] = cell_id(dmg.longitude, dmg.latitude)
    log("damage snapped; median snap distance (m)", round(float(dmg.snap_m.median()), 1),
        "p90", round(float(dmg.snap_m.quantile(0.9)), 1))
    return dmg


# ---------------------------------------------------------------- cells
def build_cells(prem, assets):
    g = assets.groupby("cell")
    poles = assets[assets.asset_type == "pole"]
    prim = assets[assets.asset_type == "primary"]
    cells = pd.DataFrame(index=sorted(set(assets.cell) | set(prem.cell)))
    cells["poles"] = poles.groupby("cell").size()
    cells["pole_age"] = 2026 - poles.groupby("cell").install_year.mean()
    cells["primary_km"] = prim.groupby("cell").length_m.sum() / 1000
    cells["transformers"] = g.apply(lambda x: (x.asset_type == "transformer").sum(), include_groups=False)
    cells["premises"] = prem.groupby("cell").size()
    cells["customers"] = prem.groupby("cell").customers.sum()
    cells["overhead_share"] = prem.groupby("cell").overhead.mean()
    cells = cells.fillna({"poles": 0, "primary_km": 0, "transformers": 0, "premises": 0, "customers": 0})
    cells["pole_age"] = cells.pole_age.fillna(cells.pole_age.median())
    cells["overhead_share"] = cells.overhead_share.fillna(0.5)
    lon, lat = cell_center(cells.index.to_numpy())
    cells["lon"], cells["lat"] = lon, lat
    cells.index.name = "cell"
    log("cells", len(cells), "with poles", int((cells.poles > 0).sum()))
    return cells


# ---------------------------------------------------------------- facilities + zcta
def build_facilities():
    tr = Transformer.from_crs(3857, 4326, always_xy=True)
    out = []
    for name, kind in (("Hospitals_Medic_Pairwis_Clip", "hospital"), ("Fire_Stations_E_Pairwis_Clip", "fire"),
                       ("Ambulance_Servi_Pairwis_Clip", "ems")):
        r = layer(name)
        for sr in r.iterShapeRecords():
            x, y = sr.shape.points[0]
            lon, lat = tr.transform(x, y)
            out.append(dict(kind=kind, name=sr.record["NAME"], lon=round(lon, 5), lat=round(lat, 5)))
    (PROCESSED / "facilities.json").write_text(json.dumps(out, indent=1))
    log("facilities", Counter(f["kind"] for f in out))


def fetch_zcta():
    path = PROCESSED / "zcta.geojson"
    if path.exists():
        return json.loads(path.read_text())
    url = ("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/"
           "PUMA_TAD_TAZ_UGA_ZCTA/MapServer/7/query")
    params = dict(geometry=",".join(map(str, BBOX)), geometryType="esriGeometryEnvelope", inSR=4326,
                  spatialRel="esriSpatialRelIntersects", outFields="*", outSR=4326, f="geojson",
                  returnGeometry="true")
    res = httpx.get(url, params=params, timeout=120)
    res.raise_for_status()
    gj = res.json()
    for f in gj["features"]:
        props = f["properties"]
        z = props.get("ZCTA5") or props.get("BASENAME") or props.get("GEOID")
        f["properties"] = {"zip": str(z)}
    path.write_text(json.dumps(gj))
    log("zcta polygons", len(gj["features"]))
    return gj


def assign_zip(prem, gj):
    geoms = [shape(f["geometry"]) for f in gj["features"]]
    zips = [f["properties"]["zip"] for f in gj["features"]]
    tree = STRtree(geoms)
    out = []
    for lon, lat in zip(prem.lon, prem.lat):
        pt = Point(lon, lat)
        hit = [i for i in tree.query(pt) if geoms[i].contains(pt)]
        out.append(zips[hit[0]] if hit else "")
    prem["zip"] = out
    log("zip assigned", int((prem.zip != "").sum()), "of", len(prem), "zips", prem.zip.nunique())


def main():
    prem = load_premises()
    dev, chains = load_topology(prem)
    assets = build_assets(prem, dev, chains)
    dmg = build_damage(assets)
    cells = build_cells(prem, assets)
    build_facilities()
    try:
        assign_zip(prem, fetch_zcta())
    except Exception as e:  # offline: ZIP stays blank, circuit-level views still work
        log("ZCTA fetch failed:", e)
        prem["zip"] = ""
    prem.to_pickle(PROCESSED / "premises.pkl")
    dev.to_pickle(PROCESSED / "devices.pkl")
    chains.to_pickle(PROCESSED / "chains.pkl")
    assets.to_pickle(PROCESSED / "assets.pkl")
    dmg.to_pickle(PROCESSED / "damage.pkl")
    cells.to_pickle(PROCESSED / "cells.pkl")
    log("done")


if __name__ == "__main__":
    main()
