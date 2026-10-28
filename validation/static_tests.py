"""Analyse the team's XtraDAQ static thrust-stand logs (.ulg): full-throttle points, thrust-vs-power
curves from the throttle ramp, battery resistance, sensor offsets.

Run:  python static_tests.py <folder with .ulg files>   -> results/static_tests/*.csv, *.png
"""
import glob
import os
import re
import sys

import numpy as np

from ulog_reader import read_ulog

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results", "static_tests")
CH_THR, LO, HI = 2, 172, 1810            # CRSF throttle channel and its range


def prop_name(path):
    m = re.search(r"-(\d+)_(\d+)\.ulg$", path)
    d, p = m.group(1), m.group(2)
    pitch = {"75": "7.5"}.get(p, p)
    return f"{d}x{pitch}", float(d), float(pitch)


def load(path):
    u = read_ulog(path)
    T = u["topics"]
    p, th, rc, b, h = (T[(n, 0)] for n in ("power", "thrust", "rc_channels", "baro", "hum"))
    ts = lambda x: x["timestamp"].astype(float) / 1e6
    t0 = ts(p)[0]
    d = dict(t0=t0, t=ts(p) - t0, V=p["volt_mv"] / 1000.0, I=p["curr_ma"] / 1000.0, P=p["power_mw"] / 1000.0)
    d["tf"], d["F"] = ts(th) - t0, th["force_n"].astype(float)
    d["tr"] = ts(rc) - t0
    d["thr"] = (rc["channels_us"][:, CH_THR].astype(float) - LO) / (HI - LO) * 100
    # resample everything onto the thrust-cell timestamps (the slowest sensor, ~11 Hz)
    for k in ("V", "I", "P"):
        # average the 90 Hz power samples over each thrust interval to match the HX711 averaging
        edges = np.concatenate([[d["tf"][0] - 0.09], d["tf"]])
        idx = np.searchsorted(d["t"], edges)
        d[k + "f"] = np.array([d[k][a:b_].mean() if b_ > a else np.nan for a, b_ in zip(idx[:-1], idx[1:])])
    d["thrf"] = np.interp(d["tf"], d["tr"], d["thr"])
    pres = float(np.mean(b["press_hpa"])) * 100
    temp = float(np.mean(h["temp_cdeg"])) / 100
    d["rho"] = pres / (287.05 * (temp + 273.15))
    d["pres"], d["temp"] = pres, temp
    return d


def track_rpm(path, d, nfft=384, hop=48, f_lo=12.0, f_hi=235.0):
    """Propeller rpm from the once-per-revolution vibration line in the board's IMU (~480 Hz).

    Returns (t, rpm, snr_db) per STFT frame; rpm is NaN where the line is not clear. The search starts
    at the full-throttle hold (strongest line) and follows the line backwards and forwards in time,
    allowing at most 6 Hz of change between frames."""
    im = read_ulog(path)["topics"][("imu", 0)]
    t = im["timestamp"].astype(float) / 1e6
    fs = 1 / np.median(np.diff(t))
    tu = np.arange(t[0], t[-1], 1 / fs)
    sigs = [np.interp(tu, t, im[k].astype(float)) for k in ("xacc_mg_raw", "yacc_mg_raw", "zacc_mg_raw")]
    win = np.hanning(nfft)
    starts = np.arange(0, len(tu) - nfft, hop)
    freqs = np.fft.rfftfreq(nfft, 1 / fs)
    band = (freqs >= f_lo) & (freqs <= f_hi)
    S = np.zeros((len(starts), band.sum()))
    for s in sigs:
        frames = np.stack([s[i:i + nfft] for i in starts])
        frames = (frames - frames.mean(1, keepdims=True)) * win
        S += np.abs(np.fft.rfft(frames, axis=1))[:, band] ** 2
    fb = freqs[band]
    tf = tu[starts + nfft // 2] - d["t0"]
    thr = np.interp(tf, d["tr"], d["thr"])
    noise = np.median(S, axis=1)
    f = np.full(len(tf), np.nan)
    snr = np.full(len(tf), np.nan)
    hold = np.flatnonzero(thr > 97)
    seed = hold[len(hold) // 2]
    f[seed] = fb[np.argmax(S[seed])]

    def step(i, prev):
        m = np.abs(fb - prev) <= 6.0
        if not m.any():
            return np.nan, np.nan
        j = np.flatnonzero(m)[np.argmax(S[i, m])]
        return fb[j], 10 * np.log10(S[i, j] / noise[i])

    for rng in (range(seed - 1, -1, -1), range(seed + 1, len(tf))):
        prev = f[seed]
        for i in rng:
            if thr[i] < 3:
                break
            # sub-bin refinement by parabolic interpolation around the peak
            fi, sn = step(i, prev)
            if np.isnan(fi) or sn < 8:
                continue
            k = np.argmin(np.abs(fb - fi))
            if 0 < k < len(fb) - 1:
                a, b, c = np.log(S[i, k - 1:k + 2])
                fi = fb[k] + 0.5 * (a - c) / (a - 2 * b + c) * (fb[1] - fb[0])
            f[i], snr[i], prev = fi, sn, fi
    return tf, 60 * f, snr


def analyse(path):
    name, D, pitch = prop_name(path)
    d = load(path)
    thr, F = d["thrf"], d["F"]
    idle = (thr < 0.5) & (d["tf"] < d["tf"][np.argmax(thr > 2)] - 0.5)          # before the run
    hold = np.flatnonzero(thr > 97)
    # full-throttle hold: skip the first 1.0 s (thrust cell settling), stop 0.3 s before the cut
    t_on, t_off = d["tf"][hold[0]] + 1.0, d["tf"][hold[-1]] - 0.3
    w = (d["tf"] >= t_on) & (d["tf"] <= t_off) & (thr > 97)
    full = dict(prop=name, D_in=D, pitch_in=pitch,
                hold_s=t_off - t_on, V=np.nanmean(d["Vf"][w]), I=np.nanmean(d["If"][w]), P=np.nanmean(d["Pf"][w]),
                F=F[w].mean(), F_std=F[w].std(), F_first=F[w][:5].mean(), F_last=F[w][-5:].mean(),
                V_rest=np.nanmean(d["Vf"][idle]), I_idle=np.nanmean(d["If"][idle]), F_idle=F[idle].mean(),
                rho=d["rho"], temp=d["temp"])
    # rpm from IMU vibration, averaged onto the thrust-cell samples
    tr, rpm, snr = track_rpm(path, d)
    ok = np.isfinite(rpm)
    d["rpm_track"] = (tr, rpm, snr)
    d["rpmf"] = np.where((d["tf"] >= tr[ok][0]) & (d["tf"] <= tr[ok][-1]), np.interp(d["tf"], tr[ok], rpm[ok]), np.nan)
    hw = (tr >= t_on) & (tr <= t_off) & ok
    full["rpm"] = rpm[hw].mean()
    full["rpm_std"] = rpm[hw].std()
    n = full["rpm"] / 60
    Dm = D * 0.0254
    full["CT"] = full["F"] / (d["rho"] * n ** 2 * Dm ** 4)
    full["g_per_W"] = full["F"] / 9.80665 * 1000 / full["P"]
    # ideal (momentum theory) static power for this thrust; system figure of merit = ideal / electrical
    A = np.pi * (D * 0.0254 / 2) ** 2
    full["FM_sys"] = full["F"] ** 1.5 / np.sqrt(2 * d["rho"] * A) / full["P"]
    # ramp points (rising throttle only, before the hold)
    r = (d["tf"] < d["tf"][hold[0]]) & (thr > 3) & np.isfinite(d["Pf"])
    ramp = dict(thr=thr[r], P=d["Pf"][r], I=d["If"][r], V=d["Vf"][r], F=F[r], rpm=d["rpmf"][r], t=d["tf"][r])
    # battery resistance: V = V0 - I * R over the whole run while loaded
    m = np.isfinite(d["Vf"]) & (d["If"] > 2)
    R_batt = -np.polyfit(d["If"][m], d["Vf"][m], 1)[0] if m.sum() > 20 else np.nan
    full["R_batt_mohm"] = 1000 * R_batt
    return full, ramp, d



# ---------------------------------------------------------------------------------------------
# Motor fit (full-throttle holds), derived shaft power, figures
# ---------------------------------------------------------------------------------------------
ESC = 0.95
I0_ASSUMED = 1.8          # no-load current: not measurable without a prop-off run (preset value)


def fit_motor_full_throttle(rows):
    """At 100% throttle the ESC duty is ~1, so V_batt = omega / Kv + I_motor * R with I_motor =
    I_batt * esc (the app's model). Linear least squares over the full-throttle holds."""
    V = np.array([r["V"] for r in rows])
    A = np.c_[[r["rpm"] for r in rows], [r["I"] * ESC for r in rows]]
    (a, R), *_ = np.linalg.lstsq(A, V, rcond=None)
    return 1 / a, R, V - A @ np.array([a, R])


def motor_shaft(rpm, V, I, kv, R, I0=I0_ASSUMED):
    """Motor current and shaft torque from measured rpm, battery voltage and current.
    ESC input power x efficiency = motor terminal power = (omega/Kv + I_m R) I_m."""
    kvs = kv * 2 * np.pi / 60
    w = rpm * 2 * np.pi / 60
    P_in = V * I * ESC
    I_m = (-(w / kvs) + np.sqrt((w / kvs) ** 2 + 4 * R * P_in)) / (2 * R)
    return I_m, (I_m - I0) / kvs


def make_figures(results, kv, R):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import json
    import math
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "XtraProp"))
    import bemt_model as m

    INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
    PAL = ["#2a78d6", "#eb6834", "#1baf7a", "#8a5cd1", "#c99a06", "#d6457b", "#52514e"]
    W, H, DPI = 13.33, 7.5, 150
    plt.rcParams.update({"font.size": 13, "axes.titlesize": 14, "axes.labelsize": 13,
                         "xtick.labelsize": 11, "ytick.labelsize": 11, "legend.fontsize": 12})

    def style(ax):
        ax.set_facecolor(SURFACE)
        ax.grid(True, color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color(INK2)
        ax.tick_params(colors=INK2)

    def figure(title, subtitle, ncols=1):
        fig, axes = plt.subplots(1, ncols, figsize=(W, H))
        fig.patch.set_facecolor(SURFACE)
        fig.text(0.015, 0.965, title, fontsize=22, color=INK, ha="left", va="top", weight="bold")
        fig.text(0.015, 0.905, subtitle, fontsize=13, color=INK2, ha="left", va="top")
        return fig, axes

    def save(fig, name):
        fig.tight_layout(rect=(0, 0.04, 1, 0.86))
        fig.savefig(os.path.join(OUT, name), dpi=DPI, facecolor=SURFACE)
        plt.close(fig)
        print("wrote", name)

    def clean_ramp(full, ramp):
        ok = np.isfinite(ramp["P"])
        if full["prop"] == "12x7":                     # load cell bound up between 14 and 19.6 s
            ok &= ~((ramp["t"] > 14) & (ramp["t"] < 19.6))
        return ok

    order = sorted(range(len(results)), key=lambda i: -results[i][0]["F_at_300W"])
    color = {results[i][0]["prop"]: PAL[k] for k, i in enumerate(order)}
    src = "XtraDAQ static tests · EMAX GT2820/06 · 3S · thrust: HX711 load cell, rpm: IMU vibration line"

    # 1. thrust vs electrical power
    fig, ax = figure("Static thrust vs. electrical power", src)
    style(ax)
    for i in order:
        full, ramp, _ = results[i]
        ok = clean_ramp(full, ramp) & (ramp["P"] > 15)
        P, F = ramp["P"][ok], ramp["F"][ok]
        o = np.argsort(P)
        c = color[full["prop"]]
        ax.plot(P[o], F[o], ".", color=c, markersize=3, alpha=0.35)
        pf = np.linspace(40, full["P"], 60)
        ax.plot(pf, full["fit_a"] * pf ** full["fit_b"], color=c, linewidth=2.2)
        ax.plot(full["P"], full["F"], "o", color=c, markersize=9, markeredgecolor=SURFACE, markeredgewidth=1.2)
        ax.annotate(full["prop"], (full["P"], full["F"]), xytext=(8, 0), textcoords="offset points",
                    va="center", color=c, fontsize=13, weight="bold")
    ax.axvline(300, color=INK2, linewidth=1, linestyle=(0, (4, 3)))
    ax.text(302, 1, "300 W", color=INK2, fontsize=11)
    ax.set_xlabel("Electrical power from the battery [W]", color=INK)
    ax.set_ylabel("Thrust [N]", color=INK)
    ax.set_xlim(0, 520)
    ax.set_ylim(0, 24)
    fig.text(0.015, 0.02, "Small dots: throttle ramp (≈11 Hz). Large dot: full-throttle hold (mean). "
             "12x7: 14–19.6 s removed (stand binding).", fontsize=11, color=INK2)
    save(fig, "06_static_thrust_vs_power.png")

    # 2. full throttle vs fair comparison
    fig, (a1, a2) = figure("Which prop gives the most thrust?",
                           "Left: at full throttle (each test drew a different power). "
                           "Right: at the same 300 W, the fair comparison.", ncols=2)
    labels = [results[i][0]["prop"] for i in order]
    y = np.arange(len(order))[::-1]
    for ax, key, xl in ((a1, "F", "Thrust at full throttle [N]"), (a2, "F_at_300W", "Thrust at 300 W [N]")):
        style(ax)
        ax.grid(axis="y", visible=False)
        vals = [results[i][0][key] for i in order]
        ax.barh(y, vals, color=[color[l] for l in labels], height=0.62)
        for yy, v, i in zip(y, vals, order):
            f = results[i][0]
            extra = (f"   {f['P']:.0f} W · {f['I']:.1f} A · {f['rpm']:.0f} rpm" if key == "F"
                     else f"   {v / 9.80665 * 1000 / 300:.1f} g/W")
            ax.text(v, yy, f" {v:.1f}" + extra, va="center", color=INK, fontsize=11)
        ax.set_yticks(y, labels)
        ax.set_xlabel(xl, color=INK)
        ax.set_xlim(0, 36 if key == "F" else 27)
    save(fig, "07_static_ranking.png")

    # 3. coefficients
    fig, (a1, a2) = figure("Measured propeller coefficients",
                           f"$C_T$ from load cell + rpm (motor-independent). $C_P$ derived through the fitted motor "
                           f"(Kv {kv:.0f}, R {R * 1000:.0f} mΩ, I0 {I0_ASSUMED} A assumed).", ncols=2)
    for ax in (a1, a2):
        style(ax)
    for i in order:
        full, ramp, _ = results[i]
        ok = clean_ramp(full, ramp) & np.isfinite(ramp["rpm"]) & (ramp["rpm"] > 3000)
        D = full["D_in"] * 0.0254
        n = ramp["rpm"][ok] / 60
        _, Q = motor_shaft(ramp["rpm"][ok], ramp["V"][ok], ramp["I"][ok], kv, R)
        CT = ramp["F"][ok] / (full["rho"] * n ** 2 * D ** 4)
        CP = 2 * np.pi * Q / (full["rho"] * n ** 2 * D ** 5)
        c = color[full["prop"]]
        for ax, v in ((a1, CT), (a2, CP)):
            ax.plot(ramp["rpm"][ok], v, ".", color=c, markersize=4, alpha=0.6)
            ax.annotate(full["prop"], (ramp["rpm"][ok][-1], np.median(v[-8:])), xytext=(6, 0),
                        textcoords="offset points", va="center", color=c, fontsize=12, weight="bold")
    a1.set_ylabel("$C_T = T / (\\rho n^2 D^4)$", color=INK)
    a2.set_ylabel("$C_P = P_{shaft} / (\\rho n^3 D^5)$", color=INK)
    for ax in (a1, a2):
        ax.set_xlabel("Propeller speed [rpm]", color=INK)
        ax.set_xlim(3000, 10300)
    a1.set_ylim(0, 0.2)
    a2.set_ylim(0, 0.09)
    save(fig, "08_static_coefficients.png")

    # 4. 10x6 vs the app's model (Aero-naut CAM 10x6 preset + GT2820/06 team-rig motor)
    presets = json.load(open(os.path.join(os.path.dirname(HERE), "XtraProp", "presets.json"), encoding="utf-8"))
    full, ramp, _ = [r for r in results if r[0]["prop"] == "10x6"][0]
    prop = m.from_preset(m.Propeller, presets["propellers"]["10 x 6 Aeronaut CAM Carbon"])
    af = m.prop_airfoil(prop)
    atm = m.atmosphere_from(0, full["temp"], rho=full["rho"])
    rpms = np.linspace(3000, 9600, 23)
    TQ = np.array([m.calc_thrust(prop, af, 0.0, r * 2 * np.pi / 60, atm) for r in rpms])
    kvs = kv * 2 * np.pi / 60
    I_m = I0_ASSUMED + TQ[:, 1] * kvs
    P_el = (rpms * 2 * np.pi / 60 / kvs + I_m * R) * I_m / ESC
    ok = np.isfinite(ramp["rpm"]) & (ramp["rpm"] > 3000)
    fig, (a1, a2) = figure("10x6: measured vs. XtraProp model (same motor)",
                           "Model: '10 x 6 Aeronaut CAM Carbon' preset + GT2820/06 fitted to these tests. "
                           "Is the tested 10x6 an Aero-naut CAM?", ncols=2)
    for ax, mv, yv, yl in ((a1, TQ[:, 0], ramp["F"], "Thrust [N]"), (a2, P_el, ramp["P"], "Electrical power [W]")):
        style(ax)
        ax.plot(ramp["rpm"][ok], yv[ok], "o", color=INK, markersize=4, alpha=0.6, label="Measured (ramp)")
        ax.plot(rpms, mv, color=PAL[0], linewidth=2.4, label="XtraProp model")
        ax.set_xlabel("Propeller speed [rpm]", color=INK)
        ax.set_ylabel(yl, color=INK)
        ax.legend(frameon=False, loc="upper left")
    i = np.argmin(abs(rpms - full["rpm"]))
    T_mod = np.interp(full["rpm"], rpms, TQ[:, 0])
    P_mod = np.interp(full["rpm"], rpms, P_el)
    fig.text(0.015, 0.02, f"At the full-throttle {full['rpm']:.0f} rpm: thrust model {T_mod:.1f} N vs measured "
             f"{full['F']:.1f} N ({100 * (T_mod / full['F'] - 1):+.0f}%), power model {P_mod:.0f} W vs measured "
             f"{full['P']:.0f} W ({100 * (P_mod / full['P'] - 1):+.0f}%).", fontsize=11, color=INK2)
    save(fig, "09_static_10x6_vs_model.png")
    return dict(T_mod=T_mod, P_mod=P_mod)


def run(folder):
    import csv
    os.makedirs(OUT, exist_ok=True)
    files = sorted(glob.glob(os.path.join(folder, "*.ulg")), key=lambda p: p.split("-")[-2])
    results = [analyse(f) for f in files]
    rows = [r[0] for r in results]
    for full, ramp, _ in results:
        ok = np.isfinite(ramp["P"]) & (ramp["P"] > 60)
        if full["prop"] == "12x7":
            ok &= ~((ramp["t"] > 14) & (ramp["t"] < 19.6))
        b, a = np.polyfit(np.log(ramp["P"][ok]), np.log(np.maximum(ramp["F"][ok], 0.1)), 1)
        full["fit_a"], full["fit_b"] = float(np.exp(a)), float(b)
        full["F_at_300W"] = full["fit_a"] * 300 ** b
    kv, R, resid = fit_motor_full_throttle(rows)
    print(f"Motor fit from the full-throttle holds: Kv {kv:.0f} rpm/V, R (motor+ESC+wiring) {R * 1000:.1f} mOhm, "
          f"voltage residual RMS {1000 * np.sqrt(np.mean(resid ** 2)):.0f} mV")
    for f in rows:
        I_m, Q = motor_shaft(f["rpm"], f["V"], f["I"], kv, R)
        n, D = f["rpm"] / 60, f["D_in"] * 0.0254
        f["Q"] = float(Q)
        f["P_shaft"] = float(Q * 2 * np.pi * n)
        f["eta_drive"] = f["P_shaft"] / f["P"]
        f["CP"] = float(2 * np.pi * Q / (f["rho"] * n ** 2 * D ** 5))
        f["FM_prop"] = f["CT"] ** 1.5 / (f["CP"] * np.sqrt(np.pi / 2))
        f["pitch_speed_ms"] = f["pitch_in"] * 0.0254 * n
    keys = ["prop", "V_rest", "V", "I", "P", "F", "F_std", "rpm", "g_per_W", "F_at_300W", "CT", "CP", "Q",
            "P_shaft", "eta_drive", "FM_prop", "pitch_speed_ms", "R_batt_mohm", "rho", "temp"]
    with open(os.path.join(OUT, "static_tests_summary.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(keys)
        for f in rows:
            w.writerow([f[k] if isinstance(f[k], str) else round(float(f[k]), 4) for k in keys])
    for f in rows:
        print(f"{f['prop']:6s} full: {f['F']:5.2f} N {f['P']:5.0f} W {f['I']:4.1f} A {f['rpm']:5.0f} rpm "
              f"{f['g_per_W']:.2f} g/W | @300W {f['F_at_300W']:5.2f} N | CT {f['CT']:.3f} CP {f['CP']:.4f} "
              f"FM {f['FM_prop']:.2f} drive eff {f['eta_drive']:.2f} pitch speed {f['pitch_speed_ms']:.1f} m/s")
    print(make_figures(results, kv, R))
    return results, kv, R


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "/home/claude/ulog_data")
