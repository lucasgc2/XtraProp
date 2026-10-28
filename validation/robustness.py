"""Automated robustness checks for XtraProp's model (numerics, physics limits, edge cases,
geometry import, shipped presets, random fuzzing).

Run from this folder:  python robustness.py
Exits with status 1 if any check fails.
"""
import json
import math
import os
import random
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(os.path.dirname(HERE), "XtraProp")
sys.path.insert(0, APP)
import bemt_model as m          # noqa: E402
import build_apc_presets as apc  # noqa: E402

AF = m.load_airfoil("NACA4412 Ncrit5")
ATM = m.atmosphere_from(0, 15)
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


def coeffs(prop, airfoil, rpm, J):
    n = rpm / 60
    D = 2 * prop.r_tip
    T, Q = m.calc_thrust(prop, airfoil, J * n * D, 2 * math.pi * n, ATM)
    return T / (ATM.rho * n ** 2 * D ** 4), 2 * math.pi * Q / (ATM.rho * n ** 2 * D ** 5)


def apc_prop(name="10x7", n_elem=20):
    preset = apc.validation_preset(name)
    preset["num_elm"] = n_elem
    prop = m.from_preset(m.Propeller, preset)
    return prop, m.prop_airfoil(prop)


# ------------------------------------------------------------------ numerics

def grid_independence():
    p_ref, af = apc_prop(n_elem=320)
    ref = {J: coeffs(p_ref, af, 5000, J) for J in (0.0, 0.4)}
    errs = {}
    for n in (10, 20, 40, 80):
        p, _ = apc_prop(n_elem=n)
        e = []
        for J, (ct_r, cp_r) in ref.items():
            ct, cp = coeffs(p, af, 5000, J)
            e += [abs(ct / ct_r - 1), abs(cp / cp_r - 1)]
        errs[n] = 100 * max(e)
        print(f"      {n:4d} elements: max change vs 320 = {errs[n]:.2f}%")
    check("Grid independence: default 20 elements within 1% of converged", errs[20] < 1.0, f"{errs[20]:.2f}%")


def iteration_tolerance():
    p, af = apc_prop()
    cases = [(rpm, J) for rpm in (3000, 6000) for J in (0, 0.3, 0.6, 0.8)]
    base = [coeffs(p, af, *c) for c in cases]
    old = (m.BEMT_TOL, m.BEMT_ITERATIONS)
    m.BEMT_TOL, m.BEMT_ITERATIONS = 1e-10, 5000
    tight = [coeffs(p, af, *c) for c in cases]
    m.BEMT_TOL, m.BEMT_ITERATIONS = old
    diff = max(abs(a - b) for x, y in zip(base, tight) for a, b in zip(x, y))
    check("Inner-loop tolerance: default vs 1e-10 agree", diff < 1e-4, f"max |dC| = {diff:.1e}")


# ------------------------------------------------------------------ physics

def momentum_limit():
    worst = 0.0
    for name in apc.VALIDATION_PRESETS:
        p, af = apc_prop(name)
        A = math.pi * p.r_tip ** 2
        for rpm in (2000, 4000, 6000, 9000):
            om = 2 * math.pi * rpm / 60
            T, Q = m.calc_thrust(p, af, 0.0, om, ATM)
            worst = max(worst, T ** 1.5 / math.sqrt(2 * ATM.rho * A) / (Q * om))
    check("Static figure of merit below ideal momentum limit (FM < 1)", worst < 1.0, f"max FM = {worst:.3f}")
    check("Static figure of merit realistic for small props (FM < 0.8)", worst < 0.8, f"max FM = {worst:.3f}")


def motor_setup(diameter=10, pitch=6, kv=985, r_motor=0.055, i0=1.8, cells=3, blades=2, n_elem=20):
    R = diameter * m.INCH / 2
    prop = m.Propeller(name="t", diameter_inch=diameter, r_hub=0.15 * R, root_chord=0.2 * R,
                       tip_chord=0.06 * R, root_pitch=0, tip_pitch=0, pitch_inch=pitch,
                       blades=blades, num_elm=n_elem)
    motor = m.Motor(name="t", KV=kv, R_motor=r_motor, I_loadfree=i0, max_current=50, max_power=500, weight_g=100)
    bat = m.Battery(name="t", cells=cells, nominal_voltage=3.7 * cells, max_voltage=4.2 * cells,
                    capacity_mah=3000, discharge_c=40, internal_resistance=0.005 * cells)
    return prop, motor, bat


def physics(pt, motor, bat, label, esc=m.DEFAULT_ESC_EFFICIENCY):
    vals = [pt.thrust, pt.torque, pt.rpm, pt.I_motor, pt.I_battery, pt.shaft_power]
    if any(not math.isfinite(x) for x in vals):
        return [f"{label}: non-finite result"]
    bad = []
    V = pt.throttle * bat.max_voltage
    if pt.rpm > motor.KV * V * 1.0001 + 1:
        bad.append(f"{label}: rpm above no-load speed")
    if pt.rpm < -1e-6:
        bad.append(f"{label}: negative rpm")
    if not pt.windmilling and pt.shaft_power > pt.elec_power * 1.0001 + 1e-6:
        bad.append(f"{label}: shaft power exceeds battery power")
    if pt.I_motor > V / (motor.R_motor + bat.internal_resistance) * 1.0001 + 1e-6:
        bad.append(f"{label}: current above stall current")
    if pt.I_motor > 0 and abs(pt.I_battery - pt.throttle * pt.I_motor / esc) > 1e-9:
        bad.append(f"{label}: battery current inconsistent with ESC efficiency")
    if pt.prop_efficiency > 0.92:
        bad.append(f"{label}: prop efficiency {pt.prop_efficiency:.2f} unrealistically high")
    return bad


def monotonic_thrust():
    prop, motor, bat = motor_setup()
    worst = 0.0
    for thr in (0.3, 0.6, 1.0):
        T = [m.motor_battery(prop, AF, motor, bat, thr, V, ATM).thrust for V in np.linspace(0, 35, 36)]
        # only while producing thrust: once braking (T < 0) the tip passes negative stall
        worst = max(worst, max([b - a for a, b in zip(T, T[1:]) if a > 0], default=0.0))
    check("Thrust never rises with airspeed at fixed throttle (while T > 0)", worst <= 1e-6, f"largest rise {worst:.1e} N")


def low_re_drag():
    re_min = AF.re_values[0]
    _, cd0 = AF.coeffs(4.0, re_min)
    _, cd1 = AF.coeffs(4.0, re_min / 4)
    expect = (0.25) ** m.LOW_RE_DRAG_EXPONENT
    check("Low-Re drag scaling: Cd at Re_min/4 = Cd(Re_min) x 4^0.5", abs(cd1 / cd0 - expect) < 1e-9,
          f"ratio {cd1 / cd0:.3f}")
    _, cd_hi = AF.coeffs(4.0, AF.re_values[-1] * 10)
    _, cd_top = AF.coeffs(4.0, AF.re_values[-1])
    check("Above the highest polar Re, drag is held constant", abs(cd_hi - cd_top) < 1e-12)


# ------------------------------------------------------------------ geometry + presets

def geometry_import():
    info = m.read_geometry_file(os.path.join(HERE, "fixtures", "10x7E-PERF.PE0"))
    g = np.array(info["geometry"])
    ok = (abs(info["diameter_inch"] - 10) < 1e-9 and abs(info["r_hub"] - 1.1 * m.INCH) < 1e-9
          and abs(g[0, 0] - 0.22) < 1e-6 and abs(g[-1, 0] - 1.0) < 1e-6
          # file rows at 2.4307 in (24.6239 deg) and 2.5528 in (23.5776 deg) -> 24.03 deg at 2.5 in
          and abs(np.interp(0.5, g[:, 0], g[:, 2]) - 24.03) < 0.01)
    check("APC PE0 import: diameter, hub, stations and twist read correctly", ok,
          f"{len(g)} stations, beta(0.5R) = {np.interp(0.5, g[:, 0], g[:, 2]):.2f} deg")
    check("APC PE0 import: E63 root replaced by tip section (validated rule)",
          info["root_airfoil"] == info["tip_airfoil"] == "APC12",
          f"{info['root_airfoil']} -> {info['tip_airfoil']}")
    uiuc = m.read_geometry_file(os.path.join(HERE, "uiuc", "apce_10x7_geom.txt"))
    check("UIUC geometry import: 18 stations from r/R = 0.15", len(uiuc["geometry"]) == 18
          and abs(uiuc["r_hub_frac"] - 0.15) < 1e-9)
    bad = []
    for table in ([[0.5, 0.1, 10]], [[0.5, 0.1, 10], [0.4, 0.1, 9]], [[0.2, -0.1, 10], [1, 0.05, 9]],
                  [[0.2, 0.1, 95], [1, 0.05, 9]], [[0.2, 0.1, 10], [1.2, 0.05, 9]]):
        try:
            m.validate_geometry(table)
            bad.append(str(table))
        except ValueError:
            pass
    check("Invalid geometry tables are rejected", not bad, "; ".join(bad))


def old_presets_unchanged():
    """A preset saved before this update (no geometry/blend fields) must give identical results."""
    old = dict(name="o", diameter_inch=10, r_hub=0.012, root_chord=0.018, tip_chord=0.008,
               root_pitch=25, tip_pitch=8, pitch_inch=6, root_airfoil="naca2412", tip_airfoil="Clark Y")
    p = m.from_preset(m.Propeller, old)
    expect = (p.r_mid - p.r_hub) / (p.r_tip - p.r_hub)
    check("Old presets: airfoil blend and geometry identical to before", np.allclose(p.span_frac, expect)
          and np.allclose(p.chord_mid, 0.018 + expect * (0.008 - 0.018)))


def shipped_presets():
    data = json.load(open(os.path.join(APP, "presets.json"), encoding="utf-8"))
    motor = m.from_preset(m.Motor, next(iter(data["motors"].values())))
    bat = m.from_preset(m.Battery, next(iter(data["batteries"].values())))
    failures = []
    for name, preset in data["propellers"].items():
        try:
            p = m.from_preset(m.Propeller, preset)
            af = m.prop_airfoil(p)
            for thr, V in ((1.0, 0.0), (0.5, 15.0)):
                failures += physics(m.motor_battery(p, af, motor, bat, thr, V, ATM), motor, bat, name)
        except Exception as exc:
            failures.append(f"{name}: {exc}")
    check(f"All {len(data['propellers'])} shipped propeller presets load and run", not failures,
          "; ".join(failures[:3]))


def motor_calibration():
    """fit_motor.py must recover known motor constants from clean synthetic measurements."""
    import fit_motor as fm
    true = m.Motor(name="truth", KV=1000, R_motor=0.045, I_loadfree=1.4, max_current=50, max_power=600, weight_g=140)
    preset = apc.apc_preset("12x6E", "APC 12x6E")
    p = m.from_preset(m.Propeller, preset)
    af = m.prop_airfoil(p)
    # battery voltage is what a wattmeter reads at the ESC input, so the generator uses a stiff supply
    bat = m.Battery(name="b", cells=4, nominal_voltage=14.8, max_voltage=16.4, capacity_mah=2200,
                    discharge_c=40, internal_resistance=0.0)
    rows = []
    for thr in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
        pt = m.motor_battery(p, af, true, bat, thr, 0.0, ATM, 0.95)
        rows.append(dict(V=16.4, I=pt.I_battery, rpm=pt.rpm, Q=None, no_load=False, full=thr == 1.0))
    kv_si = 1000 * 2 * math.pi / 60                      # no-load run, as in the recommended procedure
    rows.append(dict(V=16.4, I=1.4 / 0.95, rpm=(16.4 - 1.4 * 0.045) * kv_si * 60 / (2 * math.pi), Q=None,
                     no_load=True, full=True))
    r = fm.calibrate(rows, preset, 900, 0.08, 3.0, 0.95, fit_kv=True, atm=ATM, verbose=False)
    ok = abs(r["kv"] / 1000 - 1) < 0.01 and abs(r["R"] / 0.045 - 1) < 0.05 and abs(r["I0"] / 1.4 - 1) < 0.05
    check("Motor calibration recovers known Kv, R and I0 from synthetic data", ok,
          f"Kv {r['kv']:.0f}, R {r['R'] * 1000:.1f} mOhm, I0 {r['I0']:.2f} A (truth 1000, 45.0, 1.40)")


# ------------------------------------------------------------------ edge cases + fuzzing

def edge_cases():
    cases = [
        ("throttle 0", dict(), 0.0, 0.0), ("throttle 0.1%", dict(), 0.001, 0.0),
        ("full throttle static", dict(), 1.0, 0.0), ("deep windmilling", dict(), 0.3, 80.0),
        ("3 in prop", dict(diameter=3, pitch=2), 1.0, 0.0),
        ("30 in prop, motor stalls", dict(diameter=30, pitch=12), 1.0, 0.0),
        ("1 blade", dict(blades=1), 0.8, 10.0), ("6 blades", dict(blades=6), 0.8, 10.0),
        ("2 blade elements", dict(n_elem=2), 0.8, 5.0),
        ("Re far above polars", dict(kv=4000, diameter=5, pitch=4), 1.0, 0.0),
        ("Re far below polars", dict(kv=150, cells=2), 0.2, 0.0),
        ("12S", dict(cells=12, kv=300, diameter=18, pitch=8), 1.0, 0.0),
    ]
    failures = []
    for label, kw, thr, V in cases:
        try:
            prop, motor, bat = motor_setup(**kw)
            failures += physics(m.motor_battery(prop, AF, motor, bat, thr, V, ATM), motor, bat, label)
        except Exception as exc:
            failures.append(f"{label}: {type(exc).__name__}: {exc}")
    for esc in (0.5, 0.8, 1.0):
        prop, motor, bat = motor_setup()
        failures += physics(m.motor_battery(prop, AF, motor, bat, 0.7, 5.0, ATM, esc), motor, bat,
                            f"ESC {esc:.0%}", esc)
    for alt, temp in ((-400, 45), (4500, -30), (11000, -56)):
        try:
            prop, motor, bat = motor_setup()
            failures += physics(m.motor_battery(prop, AF, motor, bat, 1.0, 0.0, m.atmosphere_from(alt, temp)),
                                motor, bat, f"{alt} m")
        except Exception as exc:
            failures.append(f"{alt} m: {exc}")
    check(f"Edge cases ({len(cases) + 6}) run without errors or unphysical results", not failures,
          "; ".join(failures[:4]))


def fuzz(n=600, seed=1):
    rng = random.Random(seed)
    failures, wm = [], 0
    t0 = time.time()
    for i in range(n):
        d = rng.uniform(4, 20)
        kw = dict(diameter=d, pitch=rng.uniform(0.3, 1.0) * d, kv=rng.uniform(250, 3000),
                  r_motor=rng.uniform(0.01, 0.3), i0=rng.uniform(0.3, 3.0), cells=rng.randint(2, 6),
                  blades=rng.randint(2, 4))
        thr, V, esc = rng.uniform(0.05, 1.0), rng.uniform(0, 40), rng.uniform(0.85, 1.0)
        try:
            prop, motor, bat = motor_setup(**kw)
            pt = m.motor_battery(prop, AF, motor, bat, thr, V, ATM, esc)
            wm += pt.windmilling
            failures += physics(pt, motor, bat, f"case {i}", esc)
        except Exception as exc:
            failures.append(f"case {i} {kw}: {type(exc).__name__}: {exc}")
    check(f"Random fuzzing: {n} setups give physical results", not failures,
          f"{len(failures)} failures, {wm} windmilling, {time.time() - t0:.0f} s")


if __name__ == "__main__":
    for title, fn in (("Numerics", (grid_independence, iteration_tolerance)),
                      ("Physics", (momentum_limit, monotonic_thrust, low_re_drag)),
                      ("Geometry and presets", (geometry_import, old_presets_unchanged, shipped_presets, motor_calibration)),
                      ("Edge cases and fuzzing", (edge_cases, fuzz))):
        print(title)
        for f in fn:
            f()
    n_fail = sum(not ok for _, ok, _ in RESULTS)
    print(f"\n{len(RESULTS) - n_fail}/{len(RESULTS)} checks passed")
    sys.exit(1 if n_fail else 0)
