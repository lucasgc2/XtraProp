"""Fit effective blade shapes for the Aero-naut CAM folding props to UIUC wind-tunnel data.

Aero-naut doesn't publish blade geometry, and UIUC (Volume 3, Dantsker et al. 2020) published
performance but not geometry. So each blade is described by four parameters and fitted, through
the app's own BEMT solver, to the measured thrust and power coefficients:

    chord   c/R(x): rises from 0.7*cmax at the hub to cmax at x = 0.35, then tapers linearly
                    to taper*cmax at the tip                       -> cmax, taper
    twist   beta(x) = atan(pitch / (pi D x)) + washout * (x - 0.75) -> pitch, washout

The result is an *effective* blade: it reproduces the measured performance, but it is not a
measurement of the real chord and twist.

Data: uiuc_ancf/ (UIUC Propeller Data Site, Volume 3: static CT/CP vs rpm and CT/CP vs J runs;
the props were measured with a torque cell, so the test motor and power supply don't enter).

Fitting uses the static data and the lower-rpm runs; each prop's highest-rpm runs (within 10% of
its fastest run) are held out to test the fit.

Two fits are made: "individual" (all four parameters per prop) and "family" (one taper and one
washout shared by all props, cmax and pitch per prop). The family fit is the one shipped: its
shapes are physically consistent, and it lets props without data (14x6.5) be interpolated.

Run:  python fit_aeronaut.py            (fits all props and airfoil candidates, ~10-20 min)
Writes results/aeronaut_fit.json and results/aeronaut_fit.csv
"""
import glob
import json
import math
import os
import re
import sys
from multiprocessing import Pool

import numpy as np
from scipy.optimize import least_squares

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "XtraProp"))
import bemt_model as m      # noqa: E402

DATA = os.path.join(HERE, "uiuc_ancf")
OUT = os.path.join(HERE, "results")
ATM = m.atmosphere_from(230, 20)      # UIUC tunnel; CT/CP are non-dimensional, this only sets Re
R_HUB = 0.022                         # 40 mm spinner + 42 mm yoke used in the tests
X_PEAK = 0.35
ROOT_RATIO = 0.7
N_ELEM = 16                           # fitting; presets use the app default of 20
HOLDOUT_FRACTION = 0.9            # runs at >= 90% of a prop's fastest run are held out
N_STATIONS = 21

PROPS = {                             # UIUC code -> (diameter, nominal pitch) in inches
    "10x6": (10.0, 6.0), "12x6": (12.0, 6.0), "125x75": (12.5, 7.5),
    "13x8": (13.0, 8.0), "14x6": (14.0, 6.0), "14x8": (14.0, 8.0),
}
AIRFOILS = {                          # label -> (root, tip)
    "NACA 4412 (Ncrit 5)": ("NACA4412 Ncrit5", ""),
    "Clark Y (Ncrit 5)": ("Clark Y Ncrit5", ""),
    "MH114 -> MH116": ("MH114", "MH116"),
}
PRIOR = dict(taper=0.45, washout=0.0)  # weak pull towards a plain helical, moderately tapered blade
PRIOR_WEIGHT = 0.02


def load(code):
    static = np.loadtxt(glob.glob(os.path.join(DATA, f"ancf_{code}_static_*.txt"))[0], skiprows=1)
    runs = {}
    for f in sorted(glob.glob(os.path.join(DATA, f"ancf_{code}_*od_*.txt"))):
        rpm = int(re.search(r"_(\d+)\.txt$", f).group(1))
        d = np.loadtxt(f, skiprows=1, ndmin=2)
        runs[rpm] = d[d[:, 1] > -0.002]           # drop the windmilling tail
    return static, runs


def geometry(params, D):
    cmax, taper, pitch, washout = params
    x_hub = R_HUB / (D * m.INCH / 2)
    x = np.linspace(x_hub, 1.0, N_STATIONS)
    c = np.where(x < X_PEAK,
                 cmax * (ROOT_RATIO + (1 - ROOT_RATIO) * (x - x_hub) / (X_PEAK - x_hub)),
                 cmax * (1 - (1 - taper) * (x - X_PEAK) / (1 - X_PEAK)))
    beta = np.degrees(np.arctan(pitch / (math.pi * D * x))) + washout * (x - 0.75)
    return [[round(float(a), 5), round(float(b), 5), round(float(g), 3)] for a, b, g in zip(x, c, beta)]


def preset(name, params, D, root, tip, n_elem=20, source=""):
    return dict(name=name, diameter_inch=D, r_hub=R_HUB, root_chord=0.02, tip_chord=0.02,
                root_pitch=0.0, tip_pitch=0.0, root_airfoil=root, tip_airfoil=tip,
                pitch_inch=round(float(params[2]), 3), blades=2, num_elm=n_elem,
                blend_start=0.0, blend_end=1.0, geometry=geometry(params, D), geometry_source=source)


def coeffs(prop, af, rpm, J):
    n = rpm / 60
    D = 2 * prop.r_tip
    T, Q = m.calc_thrust(prop, af, J * n * D, 2 * math.pi * n, ATM)
    return T / (ATM.rho * n ** 2 * D ** 4), 2 * math.pi * Q / (ATM.rho * n ** 2 * D ** 5)


def points(code, which):
    """(rpm, J, CT, CP, CT_ref, CP_ref) rows; which = 'fit' or 'test'."""
    static, runs = load(code)
    rows = []
    if which == "fit":
        for rpm, ct, cp in static[static[:, 0] >= 1900]:
            rows.append((rpm, 0.0, ct, cp, ct, cp))
    cut = HOLDOUT_FRACTION * max(runs)
    for rpm, d in runs.items():
        if (rpm < cut) != (which == "fit"):
            continue
        ct_ref = np.interp(rpm, static[:, 0], static[:, 1])
        cp_ref = np.interp(rpm, static[:, 0], static[:, 2])
        step = 2 if which == "fit" else 1                  # thin the fit set for speed
        for J, ct, cp, _ in d[::step]:
            rows.append((rpm, J, ct, cp, ct_ref, cp_ref))
    return np.array(rows)


def residuals(params, code, root, tip, pts, n_elem=N_ELEM):
    D = PROPS[code][0]
    try:
        prop = m.from_preset(m.Propeller, preset("fit", params, D, root, tip, n_elem))
    except ValueError:
        return np.full(2 * len(pts) + 2, 10.0)
    af = m.prop_airfoil(prop)
    r = []
    for rpm, J, ct, cp, ct_ref, cp_ref in pts:
        mct, mcp = coeffs(prop, af, rpm, J)
        r += [(mct - ct) / ct_ref, (mcp - cp) / cp_ref]
    r += [PRIOR_WEIGHT * (params[1] - PRIOR["taper"]) / 0.2, PRIOR_WEIGHT * (params[3] - PRIOR["washout"]) / 10]
    return np.array(r)


def error_stats(params, code, root, tip, which, n_elem=20):
    pts = points(code, which)
    r = residuals(params, code, root, tip, pts, n_elem)[:-2].reshape(-1, 2)
    out = dict(ct_rms=100 * float(np.sqrt(np.mean(r[:, 0] ** 2))), cp_rms=100 * float(np.sqrt(np.mean(r[:, 1] ** 2))))
    if which == "fit":
        st = pts[:, 1] == 0
        out.update(static_ct=100 * float(np.mean(r[st, 0])), static_cp=100 * float(np.mean(r[st, 1])))
    return out


def fit_one(job):
    code, label = job
    root, tip = AIRFOILS[label]
    D, P = PROPS[code]
    pts = points(code, "fit")
    x0 = [0.17, 0.45, P, 1.0]
    sol = least_squares(residuals, x0, args=(code, root, tip, pts),
                        bounds=([0.08, 0.2, 0.5 * P, -15.0], [0.30, 0.9, 1.6 * P, 15.0]),
                        x_scale=[0.03, 0.1, 0.5, 2.0], diff_step=0.02, max_nfev=300)
    res = dict(code=code, airfoil=label, root=root, tip=tip, params=[float(v) for v in sol.x],
               nfev=int(sol.nfev), fit=error_stats(sol.x, code, root, tip, "fit"),
               test=error_stats(sol.x, code, root, tip, "test"))
    print(f"{code:7s} {label:22s} cmax={sol.x[0]:.3f} taper={sol.x[1]:.2f} pitch={sol.x[2]:.2f} "
          f"washout={sol.x[3]:+.1f} | fit CT {res['fit']['ct_rms']:.1f}% CP {res['fit']['cp_rms']:.1f}% "
          f"| held-out CT {res['test']['ct_rms']:.1f}% CP {res['test']['cp_rms']:.1f}%", flush=True)
    return res


# ------------------------------------------------------------------ family fit

def _prop_residuals(args):
    code, params, root, tip, pts = args
    return residuals(params, code, root, tip, pts)[:-2]


def family_params(theta, codes):
    taper, washout = theta[-2], theta[-1]
    return {c: [theta[2 * i], taper, theta[2 * i + 1], washout] for i, c in enumerate(codes)}


def fit_family(label, codes, pool):
    root, tip = AIRFOILS[label]
    pts = {c: points(c, "fit") for c in codes}
    x0, lo, hi, xs = [], [], [], []
    for c in codes:
        P = PROPS[c][1]
        x0 += [0.17, P]; lo += [0.08, 0.5 * P]; hi += [0.30, 1.6 * P]; xs += [0.03, 0.5]
    x0 += [0.45, 1.0]; lo += [0.2, -15.0]; hi += [0.9, 15.0]; xs += [0.1, 2.0]

    def fun(theta):
        prm = family_params(theta, codes)
        parts = pool.map(_prop_residuals, [(c, prm[c], root, tip, pts[c]) for c in codes])
        return np.concatenate(parts + [[PRIOR_WEIGHT * (theta[-2] - PRIOR["taper"]) / 0.2,
                                        PRIOR_WEIGHT * (theta[-1] - PRIOR["washout"]) / 10]])

    sol = least_squares(fun, x0, bounds=(lo, hi), x_scale=xs, diff_step=0.02, max_nfev=200)
    prm = family_params(sol.x, codes)
    out = []
    for c in codes:
        r = dict(code=c, airfoil=label, root=root, tip=tip, params=[float(v) for v in prm[c]], mode="family",
                 fit=error_stats(prm[c], c, root, tip, "fit"), test=error_stats(prm[c], c, root, tip, "test"))
        out.append(r)
        print(f"  {c:7s} cmax={prm[c][0]:.3f} pitch={prm[c][2]:.2f} | fit CT {r['fit']['ct_rms']:.1f}% "
              f"CP {r['fit']['cp_rms']:.1f}% | held-out CT {r['test']['ct_rms']:.1f}% CP {r['test']['cp_rms']:.1f}%",
              flush=True)
    print(f"  shared: taper={sol.x[-2]:.3f} washout={sol.x[-1]:+.2f} deg ({sol.nfev} evaluations)", flush=True)
    return out


def summarise(results, title):
    print(title)
    for label in AIRFOILS:
        rs = [r for r in results if r["airfoil"] == label]
        if rs:
            print(f"  {label:22s} fit CT {np.mean([r['fit']['ct_rms'] for r in rs]):.1f}%  CP {np.mean([r['fit']['cp_rms'] for r in rs]):.1f}%"
                  f" | held-out CT {np.mean([r['test']['ct_rms'] for r in rs]):.1f}%  CP {np.mean([r['test']['cp_rms'] for r in rs]):.1f}%")


if __name__ == "__main__" and "--family" in sys.argv:
    os.makedirs(OUT, exist_ok=True)
    labels = [a for a in AIRFOILS if a != "MH114 -> MH116"]
    results = []
    with Pool(2) as pool:
        for label in labels:
            print(f"Family fit, {label}:", flush=True)
            results += fit_family(label, list(PROPS), pool)
    with open(os.path.join(OUT, "aeronaut_family_fit.json"), "w") as f:
        json.dump(results, f, indent=1)
    summarise(results, "\nFamily fit, mean over props:")
    sys.exit(0)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    codes = sys.argv[1:] or list(PROPS)
    jobs = [(c, a) for a in AIRFOILS for c in codes]
    with Pool(2) as pool:
        results = pool.map(fit_one, jobs)
    with open(os.path.join(OUT, "aeronaut_fit.json"), "w") as f:
        json.dump(results, f, indent=1)
    summarise(results, "\nIndividual fits, mean over props (RMS of CT and CP, normalised by static values):")
