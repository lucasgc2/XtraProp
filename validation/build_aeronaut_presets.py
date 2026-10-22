"""Write the fitted Aero-naut CAM presets into presets.json.

Uses results/aeronaut_family_fit.json from `python fit_aeronaut.py --family`. Clark Y (Ncrit 5)
is used: it was slightly better than NACA 4412 on the held-out runs (CT 4.2% vs 4.8%, CP 4.4% vs
4.7% RMS) and on the 12x6.5 interpolation test (CT 2.9% vs 3.9%), see check_aeronaut.py.
The 14x6.5, which UIUC didn't test, is interpolated between the fitted 14x6 and 14x8, the scheme
check_aeronaut.py validates on the 12x6.5.

Run:  python build_aeronaut_presets.py
"""
import json
import os
import re

import fit_aeronaut as fa

AIRFOIL = "Clark Y (Ncrit 5)"
NAMES = {   # preset name in presets.json -> UIUC code
    "10 x 6 Aeronaut CAM Carbon": "10x6",
    "12 x 6 Aeronaut CAM Carbon": "12x6",
    "12.5 x 7.5 Aeronaut CAM Carbon": "125x75",
    "13 x 8 Aeronaut CAM Carbon": "13x8",
    "14 x 6 Aeronaut CAM Carbon": "14x6",
    "14 x 8 Aeronaut CAM Carbon": "14x8",
}
PRESETS = os.path.join(os.path.dirname(fa.HERE), "XtraProp", "presets.json")


def build():
    rs = {r["code"]: r for r in json.load(open(os.path.join(fa.OUT, "aeronaut_family_fit.json")))
          if r["airfoil"] == AIRFOIL}
    root, tip = fa.AIRFOILS[AIRFOIL]
    out = {}
    for name, code in NAMES.items():
        r = rs[code]
        src = (f"Fitted to UIUC wind-tunnel data (Vol. 3, ancf_{code}); effective shape, "
               f"held-out error CT {r['test']['ct_rms']:.1f}% CP {r['test']['cp_rms']:.1f}%")
        out[name] = fa.preset(name, r["params"], fa.PROPS[code][0], root, tip, source=src)
    p6, p8 = rs["14x6"]["params"], rs["14x8"]["params"]
    w = (6.5 - 6.0) / (8.0 - 6.0)
    p65 = [a + w * (b - a) for a, b in zip(p6, p8)]
    name = "14 x 6.5 Aeronaut CAM Carbon"
    out[name] = fa.preset(name, p65, 14.0, root, tip,
                          source="Interpolated between the fitted 14x6 and 14x8 (no UIUC data for 14x6.5)")
    return out


if __name__ == "__main__":
    data = json.load(open(PRESETS, encoding="utf-8"))
    for name, p in build().items():
        assert name in data["propellers"], name
        data["propellers"][name] = p
        print(f"{name:32s} cmax={max(g[1] for g in p['geometry']):.3f} pitch={p['pitch_inch']:.2f}  {p['geometry_source'][:60]}")
    data["motors"].setdefault("Hacker A30-14L V4 800KV", dict(
        name="Hacker A30-14L V4 800KV", KV=800.0, R_motor=0.033, I_loadfree=1.6,
        max_current=40.0, max_power=500.0, weight_g=143.0))
    s = json.dumps(data, indent=2, ensure_ascii=False)
    s = re.sub(r'\[\n\s+(-?[\d.]+),\n\s+(-?[\d.]+),\n\s+(-?[\d.]+)\n\s+\]', r'[\1, \2, \3]', s)
    open(PRESETS, "w", encoding="utf-8").write(s + "\n")
