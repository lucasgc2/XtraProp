"""Independent checks of the Aero-naut family fit (fit_aeronaut.py --family must have been run).

1. Interpolation test: the 14x6.5 has no published data, so it is built by interpolating cmax and
   effective pitch between the fitted 14x6 and 14x8. The same scheme is tested where data exist:
   the 12x8 is fitted (cmax and pitch only, family taper/washout kept), the 12x6.5 is then
   interpolated between 12x6 and 12x8 and compared with its UIUC measurements (never fitted).
2. End-to-end: the fitted 10x6 is run through the motor model against the Tyto thrust-stand test.

Run:  python check_aeronaut.py
"""
import json
import os

import numpy as np
from scipy.optimize import least_squares

import fit_aeronaut as fa
import tyto_check

RESULTS = os.path.join(fa.OUT, "aeronaut_family_fit.json")
fa.PROPS.update({"12x8": (12.0, 8.0), "12x65": (12.0, 6.5)})


def family(label):
    rs = [r for r in json.load(open(RESULTS)) if r["airfoil"] == label]
    return {r["code"]: r["params"] for r in rs}


def all_points(code):
    pts = np.vstack([fa.points(code, "fit"), fa.points(code, "test")])
    return pts


def fit_cmax_pitch(code, label, taper, washout):
    root, tip = fa.AIRFOILS[label]
    pts = all_points(code)
    P = fa.PROPS[code][1]

    def res(x):
        return fa.residuals([x[0], taper, x[1], washout], code, root, tip, pts)[:-2]
    sol = least_squares(res, [0.15, P], bounds=([0.08, 0.5 * P], [0.3, 1.6 * P]), x_scale=[0.03, 0.5],
                        diff_step=0.02, max_nfev=100)
    return [float(sol.x[0]), taper, float(sol.x[1]), washout]


def interpolate(p_lo, p_hi, P_lo, P_hi, P):
    w = (P - P_lo) / (P_hi - P_lo)
    return [a + w * (b - a) for a, b in zip(p_lo, p_hi)]


def score(params, code, label):
    root, tip = fa.AIRFOILS[label]
    r = fa.residuals(params, code, root, tip, all_points(code), n_elem=20)[:-2].reshape(-1, 2)
    st = all_points(code)[:, 1] == 0
    return dict(ct_rms=100 * float(np.sqrt(np.mean(r[:, 0] ** 2))), cp_rms=100 * float(np.sqrt(np.mean(r[:, 1] ** 2))),
                static_ct=100 * float(np.mean(r[st, 0])), static_cp=100 * float(np.mean(r[st, 1])))


if __name__ == "__main__":
    summary = {}
    for label in ("NACA 4412 (Ncrit 5)", "Clark Y (Ncrit 5)"):
        fam = family(label)
        taper, washout = fam["10x6"][1], fam["10x6"][3]
        p12x8 = fit_cmax_pitch("12x8", label, taper, washout)
        p12x65 = interpolate(fam["12x6"], p12x8, 6.0, 8.0, 6.5)
        s_interp = score(p12x65, "12x65", label)
        root, tip = fa.AIRFOILS[label]
        preset = fa.preset("10x6", fam["10x6"], 10.0, root, tip)
        _, all_pts, hi_pts = tyto_check.run(preset, verbose=False)
        summary[label] = dict(p12x8=p12x8, p12x65=p12x65, interp=s_interp, tyto=all_pts, tyto_hi=hi_pts)
        print(f"{label}:")
        print(f"  12x8 fit: cmax={p12x8[0]:.3f} pitch={p12x8[2]:.2f}")
        print(f"  12x6.5 interpolated, vs its UIUC data: CT RMS {s_interp['ct_rms']:.1f}%  CP RMS {s_interp['cp_rms']:.1f}%"
              f"  static CT {s_interp['static_ct']:+.1f}%  static CP {s_interp['static_cp']:+.1f}%")
        print(f"  Tyto 10x6 + Hacker A30-14L (all / >7000 rpm): thrust {all_pts['T']:+.1f}% / {hi_pts['T']:+.1f}%"
              f"  torque {all_pts['Q']:+.1f}% / {hi_pts['Q']:+.1f}%  current {all_pts['I']:+.1f}% / {hi_pts['I']:+.1f}%")
    with open(os.path.join(fa.OUT, "aeronaut_checks.json"), "w") as f:
        json.dump(summary, f, indent=1)
