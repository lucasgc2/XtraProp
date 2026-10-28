"""Fit a motor's constants (Kv, winding resistance R, no-load current I0) from thrust-stand or
wattmeter measurements, using the app's own motor model.

Measurement CSV (one row per throttle step, header names as below; extra columns are ignored):
    voltage_V   battery voltage under load, measured at the ESC input       (required)
    current_A   battery current                                             (required)
    rpm         propeller rpm (optical tachometer)                          (required)
    torque_Nm   shaft torque, if your stand measures it                     (optional)
    no_load     1 for a run with no propeller fitted, else 0 / empty        (optional)
    full        1 if the throttle was at 100% for this row, else 0 / empty  (optional, recommended)
Lines starting with # are comments.

Model (as in bemt_model.motor_battery): motor current I_m = I0 + Q * Kv_SI, motor voltage
V_m = omega / Kv_SI + I_m * R, ESC duty d = V_m / V_batt, battery current = d * I_m / esc_eff.
Q is the measured torque if given, otherwise the app's prop model at the measured rpm (so the
prop preset should be a validated one: an APC prop with its PE0 table, or a fitted CAM prop).
No-load rows (Q = 0) pin down Kv and I0 directly. Full-throttle rows (ESC duty = 100%) pin down
Kv and R through the voltage balance V_batt = omega / Kv_SI + I_m * R, which sets the rpm the app
predicts at full throttle. Part-throttle rows only constrain the losses (R and I0 together).

Every other row is held out from the fit and used to test it.

Usage:
  python fit_motor.py data.csv --prop "12 x 8.5 APC Thin Electric" [--kv 985] [--fit-kv] [--esc 0.95]
                      [--start "XtraChallenge 2027 - EMAX GT2820/06"] [--save "New motor name"]
"""
import argparse
import csv
import json
import math
import os
import sys

import numpy as np
from scipy.optimize import least_squares

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(os.path.dirname(HERE), "XtraProp")
sys.path.insert(0, APP)
import bemt_model as m      # noqa: E402

PRESETS = os.path.join(APP, "presets.json")


def read_csv(path):
    with open(path, encoding="utf-8") as f:
        lines = [ln for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    rows = []
    for r in csv.DictReader(lines):
        def num(key):
            v = (r.get(key) or "").strip()
            return float(v) if v else None
        rows.append(dict(V=num("voltage_V"), I=num("current_A"), rpm=num("rpm"),
                         Q=num("torque_Nm"), no_load=bool(num("no_load") or 0), full=bool(num("full") or 0)))
    return [r for r in rows if r["V"] and r["I"] is not None and r["rpm"]]


def shaft_torques(rows, prop_preset, atm):
    """Measured torque where available, else the prop model at the measured rpm (0 for no-load rows)."""
    prop = af = None
    if prop_preset is not None:
        prop = m.from_preset(m.Propeller, prop_preset)
        af = m.prop_airfoil(prop)
    out = []
    for r in rows:
        if r["no_load"]:
            out.append(0.0)
        elif r["Q"] is not None:
            out.append(r["Q"])
        elif prop is not None:
            out.append(float(m.calc_thrust(prop, af, 0.0, 2 * math.pi * r["rpm"] / 60, atm)[1]))
        else:
            raise ValueError("Rows without measured torque need --prop")
    return np.array(out)


def predict_current(kv, R, I0, esc, rows, Q):
    """Battery current from the app's motor model at each measured rpm and battery voltage."""
    kv_si = kv * 2 * math.pi / 60
    I = []
    for r, q in zip(rows, Q):
        omega = 2 * math.pi * r["rpm"] / 60
        I_m = I0 + q * kv_si
        V_m = omega / kv_si + I_m * R
        duty = min(V_m / r["V"], 1.0)
        I.append(duty * I_m / esc)
    return np.array(I)


def voltage_residuals(kv, R, I0, rows, Q):
    """Full-throttle and no-load rows: motor voltage must equal battery voltage (duty = 100%)."""
    kv_si = kv * 2 * math.pi / 60
    out = []
    for r, q in zip(rows, Q):
        if r.get("full") or r["no_load"]:
            omega = 2 * math.pi * r["rpm"] / 60
            I_m = I0 + q * kv_si
            out.append((omega / kv_si + I_m * R - r["V"]) / r["V"])
    return np.array(out)


def fit(rows, Q, kv0, R0, I00, esc, fit_kv):
    I_meas = np.array([r["I"] for r in rows])
    w = 1 / np.maximum(I_meas, 1.0)                 # relative error, floored at 1 A

    def unpack(x):
        return (x[0], x[1], x[2]) if fit_kv else (kv0, x[0], x[1])

    def res(x):
        kv, R, I0 = unpack(x)
        return np.concatenate([(predict_current(kv, R, I0, esc, rows, Q) - I_meas) * w,
                               3 * voltage_residuals(kv, R, I0, rows, Q)])

    x0 = ([kv0] if fit_kv else []) + [R0, I00]
    lo = ([0.5 * kv0] if fit_kv else []) + [0.001, 0.0]
    hi = ([1.5 * kv0] if fit_kv else []) + [0.5, 10.0]
    sol = least_squares(res, x0, bounds=(lo, hi))
    return unpack(sol.x)


def errors(kv, R, I0, esc, rows, Q):
    I_meas = np.array([r["I"] for r in rows])
    I_mod = predict_current(kv, R, I0, esc, rows, Q)
    rel = (I_mod - I_meas) / np.maximum(I_meas, 1.0)
    return 100 * float(np.mean(rel)), 100 * float(np.sqrt(np.mean(rel ** 2)))


def calibrate(rows, prop_preset=None, kv=None, R0=0.05, I00=1.5, esc=m.DEFAULT_ESC_EFFICIENCY,
              fit_kv=False, atm=None, verbose=True):
    atm = atm or m.atmosphere_from(0, 20)
    Q = shaft_torques(rows, prop_preset, atm)
    idx = np.arange(len(rows))
    train, test = idx[idx % 2 == 0], idx[idx % 2 == 1]     # every other row held out
    sub = lambda a, i: [a[j] for j in i] if isinstance(a, list) else a[i]
    kv_f, R_f, I0_f = fit(sub(rows, train), sub(Q, train), kv, R0, I00, esc, fit_kv)
    held = errors(kv_f, R_f, I0_f, esc, sub(rows, test), sub(Q, test))
    start = errors(kv, R0, I00, esc, sub(rows, test), sub(Q, test))
    kv_a, R_a, I0_a = fit(rows, Q, kv, R0, I00, esc, fit_kv)          # final fit on all rows
    allerr = errors(kv_a, R_a, I0_a, esc, rows, Q)
    if verbose:
        print(f"Starting values      Kv {kv:.0f}  R {R0 * 1000:.1f} mOhm  I0 {I00:.2f} A"
              f"  -> held-out current error: mean {start[0]:+.1f}%, RMS {start[1]:.1f}%")
        print(f"Fitted (half data)   Kv {kv_f:.0f}  R {R_f * 1000:.1f} mOhm  I0 {I0_f:.2f} A"
              f"  -> held-out current error: mean {held[0]:+.1f}%, RMS {held[1]:.1f}%")
        print(f"Fitted (all data)    Kv {kv_a:.0f}  R {R_a * 1000:.1f} mOhm  I0 {I0_a:.2f} A"
              f"  -> current error on all rows: mean {allerr[0]:+.1f}%, RMS {allerr[1]:.1f}%")
    return dict(kv=kv_a, R=R_a, I0=I0_a, esc=esc, held_out=held, start=start, all=allerr)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv")
    ap.add_argument("--prop", help="propeller preset name (needed unless every row has torque_Nm)")
    ap.add_argument("--start", help="motor preset to start from (its Kv, R, I0)")
    ap.add_argument("--kv", type=float, help="Kv (rpm/V); default: from --start")
    ap.add_argument("--fit-kv", action="store_true", help="also fit Kv (best with no-load rows)")
    ap.add_argument("--esc", type=float, default=m.DEFAULT_ESC_EFFICIENCY, help="ESC efficiency, 0-1")
    ap.add_argument("--save", metavar="NAME", help="save the fitted motor to presets.json under this name")
    ap.add_argument("--force", action="store_true", help="save even if the fit looks unreliable")
    a = ap.parse_args()

    presets = json.load(open(PRESETS, encoding="utf-8"))
    base = presets["motors"].get(a.start, {}) if a.start else {}
    kv = a.kv or base.get("KV")
    if not kv:
        sys.exit("Give --kv or --start")
    prop = presets["propellers"][a.prop] if a.prop else None
    res = calibrate(read_csv(a.csv), prop, kv, base.get("R_motor", 0.05), base.get("I_loadfree", 1.5),
                    a.esc, a.fit_kv)
    problems = []
    if res["held_out"][1] > 10:
        problems.append(f"held-out current error is {res['held_out'][1]:.0f}% RMS (expected below ~5%)")
    if res["R"] <= 0.0011 or res["I0"] <= 0.001 or (a.fit_kv and not 0.55 * kv < res["kv"] < 1.45 * kv):
        problems.append("a fitted value hit its limit")
    if problems:
        print("WARNING: the fit looks unreliable: " + "; ".join(problems) + ".")
        print("Check the measurements (units, rpm per motor not per blade, the right prop preset), "
              "and include a no-load row and a full-throttle row.")
    if a.save and problems and not a.force:
        sys.exit("Not saved. Fix the data, or use --force to save anyway.")
    if a.save:
        new = dict(base) if base else dict(max_current=0.0, max_power=0.0, weight_g=0.0)
        new.update(name=a.save, KV=round(res["kv"], 1), R_motor=round(res["R"], 4), I_loadfree=round(res["I0"], 3))
        m.from_preset(m.Motor, new)
        presets["motors"][a.save] = new
        m.save_presets(presets)
        print(f"Saved motor preset '{a.save}'")


if __name__ == "__main__":
    main()
