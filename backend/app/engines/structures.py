"""Damage -> parts -> labor hours, using AEP's structure drawings and the labor workbook.

Hours are read from data/Install_Labor_HackOHIO.xlsx at startup. Quantities per structure
follow the nine drawings in docs/structure_drawings.pdf. Anything the workbook does not
cover is marked as an assumption so the UI can label it.
"""
from dataclasses import dataclass, field
from functools import lru_cache

import openpyxl

from .data import WORKBOOK

DRAWING_TITLES = {
    1: "Three-phase transformer bank on crossarm",
    2: "Single-phase transformer pole",
    3: "Single-phase deadend",
    4: "Single-phase angle / tap deadend",
    5: "Single-phase tangent (pin top)",
    6: "Three-phase tap off double crossarm",
    7: "Three-phase crossarm with single-phase tap",
    8: "Three-phase deadend (35 kV, double crossarm)",
    9: "Three-phase tangent (35 kV fiberglass crossarm)",
}

PART_NAMES = {
    "POL": "Pole", "ARM": "Crossarm", "BKT": "Bracket", "ANC": "Anchor", "EQL": "Equipment lead",
    "GND": "Grounding assembly", "GYF": "Guy assembly", "DEC": "Deadend assembly",
    "INS": "Insulator", "PIN": "Pin", "REC": "Recloser", "CNC": "Connector", "XFR": "Transformer",
    "FUSE": "Fuse link / cutout", "SWI": "Switch", "VEG": "Vegetation clearing",
}


@dataclass
class Labor:
    parts: dict = field(default_factory=dict)  # code -> (install, remove)
    pole: dict = field(default_factory=dict)  # size -> (install, remove)
    xfmr: list = field(default_factory=list)  # [(kva, install, remove)]
    ilm: float = 4.5
    adders: dict = field(default_factory=dict)


@lru_cache(maxsize=1)
def labor() -> Labor:
    wb = openpyxl.load_workbook(WORKBOOK, data_only=True)
    s = wb["Labor time material related"]

    def pair(r):
        return float(s[f"A{r}"].value), float(s[f"B{r}"].value)

    lab = Labor()
    lab.parts = {"ARM": pair(3), "BKT": pair(7), "EQL": pair(40), "GND": pair(45), "GYF": pair(50),
                 "DEC": pair(55), "INS": pair(60), "PIN": pair(65), "REC": pair(70),
                 "ANC": (float(s["B35"].value), float(s["C35"].value))}
    c = wb["CNC"]
    lab.parts["CNC"] = (float(c["F3"].value), float(c["G3"].value))
    lab.pole = {sz: (float(s[f"C{r}"].value), float(s[f"D{r}"].value))
                for sz, r in (("small", 12), ("medium", 13), ("large", 14))}
    lab.xfmr = [(float(s[f"A{r}"].value), float(s[f"C{r}"].value), float(s[f"D{r}"].value))
                for r in range(19, 31)]
    lab.ilm = float(wb["Indirect Labor Multiplier"]["B1"].value)
    lw = wb["Labor only work"]
    lab.adders = {"restricted_access": float(lw["D2"].value), "confined_property": float(lw["D3"].value),
                  "remote_site": float(lw["D4"].value), "structural_realignment": float(lw["D7"].value),
                  "remote_location": float(lw["D10"].value), "specialized_handling": float(lw["D11"].value),
                  "site_complexity": float(lw["D12"].value)}
    return lab


# Assumptions where the workbook has no hours (shown as such in the UI)
ASSUMED = {
    "FUSE": (0.35, 0.15),  # refuse / replace cutout (XCO): no hours in workbook
    "SWI": (0.6, 0.3),  # switch (SWI): no hours in workbook
    "VEG": (1.0, 0.0),  # tree / limb clearing before line work: not in workbook
}

# Quantities per structure drawing (pole replacement kits)
KITS = {
    "tangent_1ph": {"INS": 2, "PIN": 1, "CNC": 2},
    "tangent_3ph": {"ARM": 1, "INS": 4, "PIN": 4, "CNC": 4},
    "deadend_1ph": {"DEC": 2, "GYF": 1, "ANC": 1, "CNC": 2},
    "deadend_3ph": {"ARM": 2, "DEC": 4, "GYF": 1, "ANC": 1, "CNC": 4},
    "angle_tap_1ph": {"DEC": 3, "GYF": 2, "ANC": 2, "GND": 1, "CNC": 3},
    "tap_3ph_crossarm": {"ARM": 2, "INS": 3, "PIN": 3, "DEC": 4, "GYF": 1, "ANC": 1, "GND": 1, "CNC": 6},
    "tap_3ph_pin": {"ARM": 1, "INS": 4, "PIN": 4, "BKT": 1, "DEC": 2, "GYF": 2, "ANC": 2, "CNC": 5},
    "transformer": {"INS": 1, "PIN": 1, "BKT": 2, "EQL": 1, "GND": 1, "CNC": 4, "FUSE": 1},
    "transformer_bank": {"ARM": 1, "INS": 3, "PIN": 3, "BKT": 4, "EQL": 3, "GND": 1, "CNC": 8, "FUSE": 3},
    "secondary": {"CNC": 3},
}


def _hours(code: str, qty: float) -> tuple[float, bool]:
    lab = labor()
    if code in lab.parts:
        i, r = lab.parts[code]
        return qty * (i + r), False
    i, r = ASSUMED[code]
    return qty * (i + r), True


def _xfmr_hours(kva: float) -> float:
    rows = labor().xfmr
    best = min(rows, key=lambda t: abs(t[0] - (kva or 25)))
    return best[1] + best[2]


def repair_kit(asset: dict, damage: dict | None = None) -> dict:
    """Parts and hours to repair one damaged asset.

    asset: a row of the assets table (dict). damage: optional ARCOS attributes
    (access_issue, special_equipment) for real records.
    """
    lab = labor()
    atype = asset["asset_type"]
    lines = []

    def add(code, qty, note=""):
        h, assumed = _hours(code, qty)
        lines.append(dict(code=code, part=PART_NAMES.get(code, code), qty=qty, hours=round(h, 3),
                          assumed=assumed, note=note))

    drawing = None
    if atype == "pole":
        structure = asset.get("structure") or "tangent_1ph"
        drawing = int(asset.get("drawing_page") or 0) or None
        size = asset.get("size_group") or "medium"
        i, r = lab.pole.get(size, lab.pole["medium"])
        lines.append(dict(code="POL", part=f"Pole ({size}, {int(asset.get('height_ft') or 40)} ft)", qty=1,
                          hours=round(i + r, 3), assumed=False, note="replace"))
        for code, qty in KITS.get(structure, KITS["tangent_1ph"]).items():
            add(code, qty)
        kva = float(asset.get("xfmr_kva") or 0)
        if kva:
            n = 3 if structure == "transformer_bank" else 1
            lines.append(dict(code="XFR", part=f"Transformer transfer ({kva:g} kVA)", qty=n,
                              hours=round(n * _xfmr_hours(kva / n), 3), assumed=False, note="remove + reinstall"))
    elif atype == "primary":
        phases = int(asset.get("phases") or 1)
        add("VEG", 1, "clear limbs / tree off line")
        add("CNC", 2 * phases, "splice")
        add("INS", phases)
        add("PIN", phases)
        if asset.get("aep_constr") == "TC Typical CrossArm" and phases >= 3:
            add("ARM", 0.25, "crossarm replaced on ~1 in 4 three-phase wire-down jobs (assumption)")
    elif atype == "secondary":
        add("VEG", 0.5, "clear limbs")
        add("CNC", 3, "splice / reconnect")
    elif atype == "transformer":
        kva = float(asset.get("kva") or 25)
        lines.append(dict(code="XFR", part=f"Transformer ({kva:g} kVA)", qty=1, hours=round(_xfmr_hours(kva), 3),
                          assumed=False, note="replace"))
        add("EQL", 1)
        add("GND", 1)
        add("CNC", 3)
        add("FUSE", 1)
    elif atype == "fuse":
        add("FUSE", 1, "refuse or replace cutout")
    elif atype == "recloser":
        add("REC", 1)
        add("EQL", 2)
        add("BKT", 1)
    elif atype == "switch":
        add("SWI", 1)
        add("EQL", 1)

    adders = []
    if damage:
        if str(damage.get("access_issue", "")) == "Yes":
            adders.append(("Restricted access", lab.adders["restricted_access"]))
        eq = str(damage.get("special_equipment") or "")
        if eq == "Backyard Bucket":
            adders.append(("Confined property access (backyard)", lab.adders["confined_property"]))
        elif eq in ("Track Hoe", "Backhoe"):
            adders.append(("Remote site access (off-road)", lab.adders["remote_site"]))
        elif eq in ("Big Bucket", "Material Handler", "Yard Dog", "Tandem Bucket", "Tandem Line", "Other"):
            adders.append((f"Specialized handling ({eq})", lab.adders["specialized_handling"]))
    if atype == "pole" and asset.get("structure") in ("angle_tap_1ph", "tap_3ph_crossarm", "tap_3ph_pin"):
        adders.append(("Site complexity (junction pole)", lab.adders["site_complexity"]))

    direct = sum(l["hours"] for l in lines) + sum(a[1] for a in adders)
    return dict(
        asset_type=atype,
        structure=asset.get("structure"),
        drawing_page=drawing,
        drawing_title=DRAWING_TITLES.get(drawing),
        lines=lines,
        adders=[dict(name=n, hours=h) for n, h in adders],
        direct_hours=round(direct, 2),
        ilm=lab.ilm,
        person_hours=round(direct * lab.ilm, 2),
        shared_pole=bool(asset.get("shared")) if atype == "pole" else False,
        uses_digger=atype == "pole",
    )


@lru_cache(maxsize=None)
def _kit_hours_cached(key: tuple) -> float:
    asset = dict(key)
    return repair_kit(asset)["direct_hours"]


def kit_direct_hours(asset: dict) -> float:
    """Direct hours without access adders (cached by the fields that matter)."""
    key = tuple(sorted((k, asset.get(k)) for k in (
        "asset_type", "structure", "size_group", "height_ft", "xfmr_kva", "phases", "aep_constr", "kva",
        "drawing_page")))
    return _kit_hours_cached(key)
