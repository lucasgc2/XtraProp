"""End-to-end check against an independent thrust-stand test (Tyto Robotics database, test 9grq):
Hacker A30-14L V4 800 kV + Aero-naut CAM Carbon Z 10x6 on ~16 V (4S), static.

For each throttle step the app's throttle is set so the predicted rpm matches the measured rpm at
the measured battery voltage; predicted thrust, torque and battery current are then compared with
the measurements. This tests the fitted 10x6 blade (a different physical prop from the UIUC one)
and the motor/ESC model with the manufacturer's motor constants.

The last two steps (1950 and 2000 us) are excluded: rpm drops although throttle rises, so the
ESC was limiting there.

Run:  python tyto_check.py
"""
import json
import os
import sys

import numpy as np
from scipy.optimize import brentq

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(os.path.dirname(HERE), "XtraProp")
sys.path.insert(0, APP)
import bemt_model as m      # noqa: E402

G = 9.80665
MOTOR = m.Motor(name="Hacker A30-14L V4 800kv", KV=800, R_motor=0.033, I_loadfree=1.6,
                max_current=40, max_power=500, weight_g=143)


def load():
    d = np.genfromtxt(os.path.join(HERE, "tyto", "hacker_a30-14l_cam_carbon_z_10x6.csv"),
                      delimiter=",", skip_header=4, names=True)
    return d[d["throttle_us"] <= 1900]


def run(prop_preset, esc_efficiency=m.DEFAULT_ESC_EFFICIENCY, atm=m.atmosphere_from(0, 20), verbose=True):
    prop = m.from_preset(m.Propeller, prop_preset)
    af = m.prop_airfoil(prop)
    rows = []
    for r in load():
        if r["rpm"] < 2500:
            continue
        bat = m.Battery(name="supply", cells=4, nominal_voltage=r["voltage_V"], max_voltage=r["voltage_V"],
                        capacity_mah=5000, discharge_c=50, internal_resistance=0.0)

        def rpm_err(thr):
            return m.motor_battery(prop, af, MOTOR, bat, thr, 0.0, atm, esc_efficiency).rpm - r["rpm"]
        if rpm_err(1.0) < 0:            # model prop too heavy: even full throttle can't reach this rpm
            thr = 1.0
        else:
            thr = brentq(rpm_err, 0.02, 1.0, xtol=1e-5)
        pt = m.motor_battery(prop, af, MOTOR, bat, thr, 0.0, atm, esc_efficiency)
        rows.append(dict(rpm=r["rpm"], rpm_model=pt.rpm, T_meas=r["thrust_kgf"] * G, T_model=pt.thrust,
                         Q_meas=r["torque_Nm"], Q_model=pt.torque,
                         I_meas=r["current_A"], I_model=pt.I_battery))
    out = {k: 100 * float(np.mean([x[f"{k}_model"] / x[f"{k}_meas"] - 1 for x in rows])) for k in ("T", "Q", "I")}
    hi = [x for x in rows if x["rpm"] > 7000]
    out_hi = {k: 100 * float(np.mean([x[f"{k}_model"] / x[f"{k}_meas"] - 1 for x in hi])) for k in ("T", "Q", "I")}
    if verbose:
        print(f"{"rpm":>6s} {"model":>6s} {"thrust meas":>11s} {'model':>7s} {'torque meas':>11s} {'model':>7s} {'current meas':>12s} {'model':>7s}")
        for x in rows:
            print(f"{x["rpm"]:6.0f} {x["rpm_model"]:6.0f} {x["T_meas"]:9.2f} N {x['T_model']:7.2f} {x['Q_meas']:9.4f} Nm {x['Q_model']:7.4f}"
                  f" {x['I_meas']:10.2f} A {x['I_model']:7.2f}")
        print(f"Mean error, all points:     thrust {out['T']:+.1f}%  torque {out['Q']:+.1f}%  current {out['I']:+.1f}%")
        print(f"Mean error, above 7000 rpm: thrust {out_hi['T']:+.1f}%  torque {out_hi['Q']:+.1f}%  current {out_hi['I']:+.1f}%")
    return rows, out, out_hi


if __name__ == "__main__":
    presets = json.load(open(os.path.join(APP, "presets.json"), encoding="utf-8"))
    run(presets["propellers"]["10 x 6 Aeronaut CAM Carbon"])
