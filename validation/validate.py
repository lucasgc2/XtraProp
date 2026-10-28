"""Validate XtraProp's propeller model against UIUC wind-tunnel measurements.

Reference data: UIUC Propeller Data Site, Volume 1, APC Thin Electric props 9x4.5, 9x6, 10x5,
10x7 and 11x5.5 (https://m-selig.ae.illinois.edu/props/volume-1/propDB-volume-1.html), in uiuc/.

Three model configurations are compared, all through the app's own code (bemt_model.py):
  before  - how the APC presets were set up before: constant 2 cm chord, constant geometric pitch,
            E63 -> Clark Y (Ncrit 9 polars) blended hub to tip, drag held constant below the
            lowest polar Reynolds number
  apc_sections - APC's published blade geometry (chord and twist table from the PE0 file) with the
            sections APC names, E63 -> NACA 4412 (Ncrit 5), blended where APC says
  after   - APC's blade geometry with NACA 4412 (Ncrit 5) along the whole blade: the setup the
            app now ships and applies when you import an APC file (bemt_model.apc_airfoil_rule)
Both APC configurations include the low-Reynolds drag scaling now in the app.

Run from this folder:  python validate.py
Writes results/summary.csv, results/points.csv and two comparison plots.
"""
import csv
import glob
import math
import os
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "XtraProp"))
import bemt_model as m                      # noqa: E402
import build_apc_presets as apc             # noqa: E402

DATA = os.path.join(HERE, "uiuc")
OUT = os.path.join(HERE, "results")
ATM = m.atmosphere_from(230, 20)            # UIUC tunnel, Urbana ~230 m; only affects Re
PROPS = ["9x4.5", "9x6", "10x5", "10x7", "11x5.5"]
CONFIGS = ["before", "apc_sections", "after"]
LABELS = {
    "before": "Before: 2 cm constant chord, const. pitch, Ncrit 9",
    "apc_sections": "APC blade table, E63 -> NACA 4412 as named by APC",
    "after": "After: APC blade table, NACA 4412 throughout (shipped)",
}


def read_table(path):
    return np.loadtxt(path, skiprows=1)


def build(name, config):
    """(Propeller, airfoil, low-Re exponent) for one UIUC prop and configuration."""
    d, p = (float(x) for x in name.split("x"))
    if config == "before":
        prop = m.Propeller(name=name, diameter_inch=d, r_hub=0.00635, root_chord=0.02, tip_chord=0.02,
                           root_pitch=0, tip_pitch=0, pitch_inch=p, root_airfoil="Eppler E63",
                           tip_airfoil="Clark Y")
        return prop, m.prop_airfoil(prop), 0.0
    preset = apc.validation_preset(name, apc_sections=(config == "apc_sections"))
    prop = m.from_preset(m.Propeller, preset)
    return prop, m.prop_airfoil(prop), -0.5


def coeffs(prop, airfoil, rpm, J):
    n = rpm / 60.0
    D = 2 * prop.r_tip
    T, Q = m.calc_thrust(prop, airfoil, J * n * D, 2 * math.pi * n, ATM)
    return T / (ATM.rho * n ** 2 * D ** 4), 2 * math.pi * Q / (ATM.rho * n ** 2 * D ** 5)


def zero_crossing(J, CT):
    for i in range(1, len(J)):
        if CT[i - 1] > 0 >= CT[i]:
            return J[i - 1] + (J[i] - J[i - 1]) * CT[i - 1] / (CT[i - 1] - CT[i])
    return float("nan")


def run():
    os.makedirs(OUT, exist_ok=True)
    points, summary, curves = [], [], {}
    saved_exponent = m.LOW_RE_DRAG_EXPONENT
    try:
        for name in PROPS:
            static = read_table(os.path.join(DATA, f"apce_{name}_static.txt"))
            runs = {int(re.search(r"_(\d+)\.txt$", f).group(1)): read_table(f)
                    for f in sorted(glob.glob(os.path.join(DATA, f"apce_{name}_[0-9]*.txt")))}
            for cfg in CONFIGS:
                prop, airfoil, exponent = build(name, cfg)
                m.LOW_RE_DRAG_EXPONENT = exponent
                s = np.array([coeffs(prop, airfoil, rpm, 0.0) for rpm in static[:, 0]])
                for (rpm, ct, cp), (mct, mcp) in zip(static, s):
                    points.append(dict(prop=name, config=cfg, rpm=rpm, J=0.0, CT_meas=ct, CP_meas=cp,
                                       CT_model=mct, CP_model=mcp))
                hi = static[:, 0] >= 3000            # low-rpm static points are at very low Re
                ct_n, cp_n, j0, deta, cr = [], [], [], [], {}
                for rpm, d in runs.items():
                    J = d[:, 0]
                    mod = np.array([coeffs(prop, airfoil, rpm, j) for j in J])
                    ct_ref = np.interp(rpm, static[:, 0], static[:, 1])
                    cp_ref = np.interp(rpm, static[:, 0], static[:, 2])
                    ct_n += list((mod[:, 0] - d[:, 1]) / ct_ref)
                    cp_n += list((mod[:, 1] - d[:, 2]) / cp_ref)
                    jm, jd = zero_crossing(J, mod[:, 0]), zero_crossing(J, d[:, 1])
                    if not math.isnan(jd):
                        j0.append(100 * (jm / jd - 1) if not math.isnan(jm) else float("nan"))
                    ok = d[:, 1] > 0.01
                    eta_m = np.where(mod[:, 1] > 0, J * mod[:, 0] / mod[:, 1], np.nan)
                    deta.append(np.nanmax(eta_m[ok]) - np.max(d[ok, 3]))
                    Jf = np.linspace(0, J.max() + 0.03, 40)
                    cr[rpm] = dict(meas=d, Jf=Jf, model=np.array([coeffs(prop, airfoil, rpm, j) for j in Jf]))
                    for j, (mct, mcp), row in zip(J, mod, d):
                        points.append(dict(prop=name, config=cfg, rpm=rpm, J=j, CT_meas=row[1], CP_meas=row[2],
                                           CT_model=mct, CP_model=mcp))
                curves[(name, cfg)] = dict(static=static, s=s, runs=cr)
                r = dict(prop=name, config=cfg,
                         static_CT_err_pct=100 * np.mean(s[hi, 0] / static[hi, 1] - 1),
                         static_CP_err_pct=100 * np.mean(s[hi, 1] / static[hi, 2] - 1),
                         curve_CT_rms_pct=100 * math.sqrt(np.mean(np.square(ct_n))),
                         curve_CP_rms_pct=100 * math.sqrt(np.mean(np.square(cp_n))),
                         zero_thrust_J_err_pct=float(np.nanmean(j0)) if j0 else float("nan"),
                         peak_eta_err=float(np.mean(deta)))
                summary.append(r)
                print(f"{name:7s} {cfg:12s} static CT {r['static_CT_err_pct']:+6.1f}%  CP {r['static_CP_err_pct']:+6.1f}%"
                      f" | curve CT {r['curve_CT_rms_pct']:5.1f}%  CP {r['curve_CP_rms_pct']:5.1f}%"
                      f" | J0 {r['zero_thrust_J_err_pct']:+5.1f}%  eta_max {r['peak_eta_err']:+.3f}")
    finally:
        m.LOW_RE_DRAG_EXPONENT = saved_exponent

    print("\nAverage absolute error over the 5 props:")
    for cfg in CONFIGS:
        rows = [r for r in summary if r["config"] == cfg]
        avg = {k: np.mean([abs(r[k]) for r in rows]) for k in
               ("static_CT_err_pct", "static_CP_err_pct", "curve_CT_rms_pct", "curve_CP_rms_pct",
                "zero_thrust_J_err_pct", "peak_eta_err")}
        print(f"  {cfg:12s} static thrust {avg['static_CT_err_pct']:5.1f}%  static power {avg['static_CP_err_pct']:5.1f}%"
              f"  curve thrust {avg['curve_CT_rms_pct']:5.1f}%  curve power {avg['curve_CP_rms_pct']:5.1f}%"
              f"  zero-thrust J {avg['zero_thrust_J_err_pct']:4.1f}%  peak eff. {avg['peak_eta_err']:.3f}")

    for fname, rows in (("summary.csv", summary), ("points.csv", points)):
        with open(os.path.join(OUT, fname), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    return summary, curves


if __name__ == "__main__":
    summary, curves = run()
    import plots
    plots.make_all(summary, curves, CONFIGS, LABELS, PROPS, OUT)
