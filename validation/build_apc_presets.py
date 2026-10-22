"""Build propeller presets from APC geometry.

apc_geometry/*.txt are extracts of APC's published PE0 geometry files
(https://www.apcprop.com/propeller-technical-data/): the RADIUS, HUBTRA and AIRFOIL1/2 lines,
then STATION (in), CHORD (in), TWIST (deg) rows. The app itself can import full PE0 files
directly (Edit propeller -> Import geometry...); this script exists so the presets shipped in
presets.json, and the props used by validate.py, are built in one reproducible way.

Run:  python build_apc_presets.py          (prints the presets as JSON)
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "XtraProp"))
import bemt_model as m      # noqa: E402

GEOM = os.path.join(HERE, "apc_geometry")


def read_extract(code):
    lines = open(os.path.join(GEOM, f"{code}.txt")).read().split("\n")
    head = {}
    rows = []
    for ln in lines:
        parts = ln.split()
        if not parts:
            continue
        if parts[0].isalpha() or parts[0].startswith("AIRFOIL"):
            head[parts[0]] = parts[1:]
        else:
            rows.append([float(x) for x in parts])
    return head, np.array(rows)


def apc_preset(code, name, diameter_inch=None, pitch_from=None, pitch_to=None, blades=2,
               note="", apc_sections=False):
    """Preset dict from an APC extract. diameter_inch rescales the blade (shape kept as r/R);
    pitch_from/pitch_to re-twists it to another geometric pitch (same planform).
    By default the app's APC rule is applied (bemt_model.APC_THICK_ROOT_RULE): APC thickens its
    E63 root section, and thin-E63 polars over-predict thrust, so the tip section is used along
    the whole blade. apc_sections=True keeps E63 -> tip section as named in the file."""
    head, rows = read_extract(code)
    R_in = float(head["RADIUS"][0])
    hubtra = float(head["HUBTRA"][0])
    a1_pos, a1 = float(head["AIRFOIL1"][0]), head["AIRFOIL1"][1]
    a2_pos, a2 = float(head["AIRFOIL2"][0]), head["AIRFOIL2"][1]

    start = [hubtra, np.interp(hubtra, rows[:, 0], rows[:, 1]), np.interp(hubtra, rows[:, 0], rows[:, 2])]
    rows = np.vstack([start, rows[rows[:, 0] > hubtra + 1e-9]])
    rr = np.minimum(rows[:, 0] / R_in, 1.0)    # last station can exceed the rounded RADIUS slightly
    cr = rows[:, 1] / R_in
    beta = rows[:, 2].copy()
    if pitch_from and pitch_to:
        r_in = rows[:, 0]
        beta += np.degrees(np.arctan(pitch_to / (2 * math.pi * r_in))
                           - np.arctan(pitch_from / (2 * math.pi * r_in)))

    D = diameter_inch or 2 * R_in
    if not apc_sections:
        a1, a2 = m.apc_airfoil_rule(a1, a2)
    library = m.list_airfoils()
    root = m.match_airfoil(a1, library)
    tip = m.match_airfoil(a2, library)
    preset = dict(
        name=name, diameter_inch=D, r_hub=round(hubtra / R_in * D / 2 * m.INCH, 5),
        root_chord=round(float(np.max(cr)) * D / 2 * m.INCH, 4),   # informative only (table is used)
        tip_chord=round(float(cr[-2]) * D / 2 * m.INCH, 4),
        root_pitch=0.0, tip_pitch=0.0,
        root_airfoil=root, tip_airfoil="" if tip == root else tip,
        pitch_inch=float(pitch_to or 0.0), blades=blades, num_elm=20,
        blend_start=round(min(a1_pos / R_in, 0.99), 3), blend_end=round(min(a2_pos / R_in, 1.0), 3),
        geometry=[[round(float(a), 5), round(float(b), 5), round(float(c), 3)] for a, b, c in zip(rr, cr, beta)],
        geometry_source=f"APC {code} PE0" + (f"; {note}" if note else ""),
    )
    if preset["blend_end"] <= preset["blend_start"]:
        preset["blend_end"] = min(preset["blend_start"] + 0.01, 1.0)
    m.from_preset(m.Propeller, preset)        # validate
    return preset


# Presets shipped with the app (names match the existing presets.json entries)
APP_PRESETS = [
    ("18x8E", "18 x 8 APC Thin Electric", {}),
    ("14x10E", "14 x 10 APC Thin Electric", {}),
    ("12x8E", "12 x 8.5 APC Thin Electric",
     dict(diameter_inch=12.0, pitch_from=8.0, pitch_to=8.5,
          note="APC makes no 12x8.5E: 12x8E planform re-twisted to 8.5 in pitch")),
    ("13x8E", "13 x 7 APC Thin Electric",
     dict(diameter_inch=13.0, pitch_from=8.0, pitch_to=7.0,
          note="APC makes no 13x7E: 13x8E planform re-twisted to 7 in pitch")),
    ("10x45MR", "10 x 4.5 APC Multi Rotor", {}),
    ("22x10", "22 x 10 APC Standard", {}),
    ("10x45MR", "10 x 4.5 Triple Blade",
     dict(blades=3, note="2-blade 10x4.5MR blade used for 3 blades (assumption)")),
    ("10x45MR", "10 x 4.5 Six Blade",
     dict(blades=6, note="2-blade 10x4.5MR blade used for 6 blades (assumption)")),
]

# Props with UIUC wind-tunnel data, built the same way, for validate.py
VALIDATION_PRESETS = {
    "9x4.5": ("9x45E", {}), "9x6": ("9x6E", {}), "10x5": ("10x5E", {}),
    "10x7": ("10x7E", {}), "11x5.5": ("11x55E", {}),
}


def app_presets():
    return {name: apc_preset(code, name, **kw) for code, name, kw in APP_PRESETS}


def validation_preset(uiuc_name, apc_sections=False):
    code, kw = VALIDATION_PRESETS[uiuc_name]
    return apc_preset(code, f"APC {code}", apc_sections=apc_sections, **kw)


if __name__ == "__main__":
    print(json.dumps(app_presets(), indent=2))
