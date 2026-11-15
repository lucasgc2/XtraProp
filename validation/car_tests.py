"""Car-mounted dynamic thrust tests (XtraDAQ v3 + pitot): thrust vs airspeed at full throttle.

Run:  python car_tests.py <folder of the unzipped archive>  -> results/car_tests/
"""
import glob
import os
import sys

import numpy as np

from ulog_reader import read_ulog

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results", "car_tests")


def load(path):
    u = read_ulog(path)
    T = u["topics"]
    ts = lambda a: a["timestamp"].astype(float) / 1e6
    p = T[("power", 0)]
    t0 = ts(p)[0]
    d = dict(path=path, params=u["params"], info=u["info"], t0=t0)
    d["t"], d["V"], d["I"] = ts(p) - t0, p["volt_mv"] / 1000.0, p["curr_ma"] / 1000.0
    th = T[("thrust", 0)]
    d["tf"], d["F"] = ts(th) - t0, th["force_n"].astype(float)
    e = T[("esc_out", 0)]
    d["te"], d["pwm"], d["armed"] = ts(e) - t0, e["pulse_us"].astype(float), e["armed"]
    a = T[("airspeed", 0)]
    d["ta"], d["ias"], d["tas"] = ts(a) - t0, a["indicated_airspeed_m_s"].astype(float), a["true_airspeed_m_s"].astype(float)
    dp = T[("differential_pressure", 0)]
    d["tdp"], d["dp"] = ts(dp) - t0, dp["differential_pressure_pa"].astype(float)
    g = T[("gps_raw", 0)]
    d["tg"], d["gs"], d["fix"] = ts(g) - t0, g["vel_cm_s"].astype(float) / 100, g["fix"]
    d["vn"], d["ve"] = g["vel_n_mm_s"] / 1000.0, g["vel_e_mm_s"] / 1000.0
    d["head"] = g["head_deg"].astype(float)
    b, h = T[("baro", 0)], T[("hum", 0)]
    d["press"], d["temp"] = float(np.median(b["press_hpa"])) * 100, float(np.median(h["temp_cdeg"])) / 100
    d["rho"] = d["press"] / (287.05 * (d["temp"] + 273.15))
    ts_ = T.get(("time_sync", 0))
    if ts_ is not None and len(ts_):
        d["utc0"] = float(ts_["utc_us"][0]) / 1e6 - (ts(ts_)[0] - t0)
    d["imu"] = T[("imu", 0)]
    return d



STAND_DRAG_M2 = 0.00313      # bare stand drag felt by the load cell, F = -0.00313 * q (fit to the no-prop runs)
STAND_MASS_KG = 0.043        # apparent moving mass on the load cell (inertia term, same fit)
PWM_FULL = 2150              # ESC range 1100-2200 us


def track_rpm(d, mask_t, f_lo=60.0, f_hi=225.0, nfft=256, hop=24, max_jump=5.0):
    """Prop rpm from the once-per-revolution vibration line in the IMU (~480 Hz).
    Searches only where mask_t(t) is true; seeds each contiguous stretch at its strongest frame
    and follows the line both ways."""
    im = d["imu"]
    t = im["timestamp"].astype(float) / 1e6 - d["t0"]
    fs = 1 / np.median(np.diff(t))
    tu = np.arange(t[0], t[-1], 1 / fs)
    sig = [np.interp(tu, t, im[k].astype(float)) for k in ("xacc_mg_raw", "yacc_mg_raw", "zacc_mg_raw")]
    starts = np.arange(0, len(tu) - nfft, hop)
    tc = tu[starts + nfft // 2]
    use = mask_t(tc)
    fr = np.fft.rfftfreq(nfft, 1 / fs)
    band = (fr >= f_lo) & (fr <= f_hi)
    fb = fr[band]
    win = np.hanning(nfft)
    S = np.zeros((len(starts), band.sum()))
    for x in sig:
        fr_ = np.stack([x[i:i + nfft] for i in starts[use]])
        fr_ = (fr_ - fr_.mean(1, keepdims=True)) * win
        S[use] += np.abs(np.fft.rfft(fr_, axis=1))[:, band] ** 2
    f = np.full(len(tc), np.nan)
    snr = np.full(len(tc), np.nan)
    noise = np.median(S, axis=1) + 1e-12
    idx = np.flatnonzero(use)
    groups = np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1) if len(idx) else []
    for g in groups:
        if len(g) < 8:
            continue
        peak = S[g].max(1) / noise[g]
        seed = g[np.argmax(peak)]
        f[seed] = fb[np.argmax(S[seed])]
        for rng in (range(seed - 1, g[0] - 1, -1), range(seed + 1, g[-1] + 1)):
            prev = f[seed]
            for i in rng:
                m = np.abs(fb - prev) <= max_jump
                j = np.flatnonzero(m)[np.argmax(S[i, m])]
                sn = 10 * np.log10(S[i, j] / noise[i])
                if sn < 10:
                    continue
                fi = fb[j]
                if 0 < j < len(fb) - 1:
                    a_, b_, c_ = np.log(S[i, j - 1:j + 2] + 1e-12)
                    den = a_ - 2 * b_ + c_
                    if den != 0:
                        fi = fb[j] + 0.5 * (a_ - c_) / den * (fb[1] - fb[0])
                f[i], snr[i], prev = fi, sn, fi
    return tc, 60 * f, snr


def full_throttle_points(d, t_window=None, settle=1.0):
    """Samples on the load-cell clock where the ESC has been at full throttle for >= settle s."""
    tf = d["tf"]
    pw = np.interp(tf, d["te"], d["pwm"])
    full = pw >= PWM_FULL
    # time since throttle reached full
    since = np.zeros_like(tf)
    for i in range(1, len(tf)):
        since[i] = since[i - 1] + (tf[i] - tf[i - 1]) if full[i] and full[i - 1] else 0.0
    ok = full & (since >= settle)
    if t_window is not None:
        ok &= (tf >= t_window[0]) & (tf <= t_window[1])
    pw_t = lambda t: np.interp(t, d["te"], d["pwm"]) >= PWM_FULL
    if t_window is not None:
        mask = lambda t: pw_t(t) & (t >= t_window[0]) & (t <= t_window[1])
    else:
        mask = pw_t
    tr, rpm, snr = track_rpm(d, mask)
    good = np.isfinite(rpm)
    # power samples averaged over each load-cell interval
    edges = np.concatenate([[tf[0] - 0.09], tf])
    ii = np.searchsorted(d["t"], edges)
    avg = lambda y: np.array([y[a:b].mean() if b > a else np.nan for a, b in zip(ii[:-1], ii[1:])])
    V, I = avg(d["V"]), avg(d["I"])
    tas = np.interp(tf, d["ta"], d["tas"])
    ias = np.interp(tf, d["ta"], d["ias"])
    gss = np.convolve(d["gs"], np.ones(5) / 5, "same")
    acc = np.interp(tf, d["tg"], np.gradient(gss, d["tg"]))
    gs = np.interp(tf, d["tg"], d["gs"])
    rpm_f = np.full(len(tf), np.nan)
    if good.sum() > 5:
        # only where a tracked frame is within 0.15 s
        near = np.abs(tf[:, None] - tr[good][None, :]).min(1) < 0.15 if good.sum() < 20000 else np.ones(len(tf), bool)
        rpm_f = np.where(near, np.interp(tf, tr[good], rpm[good]), np.nan)
    q = 0.5 * d["rho"] * tas ** 2
    F_corr = d["F"] + STAND_DRAG_M2 * q + STAND_MASS_KG * acc
    sel = ok & np.isfinite(V)
    return dict(t=tf[sel], F_raw=d["F"][sel], F=F_corr[sel], V=V[sel], I=I[sel], tas=tas[sel], ias=ias[sel],
                gs=gs[sel], acc=acc[sel], rpm=rpm_f[sel], rho=d["rho"], temp=d["temp"])


if __name__ == "__main__" and len(sys.argv) == 3:   # overview plot: <root> <out.png>
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import datetime as dt
    root = sys.argv[1]
    files = sorted(glob.glob(os.path.join(root, "*/sesion/*.ulg")))
    out = sys.argv[2]
    fig, axes = plt.subplots(len(files), 1, figsize=(15, 3.1 * len(files)))
    for ax, f in zip(axes, files):
        try:
            d = load(f)
        except KeyError:
            print(os.path.basename(f), "empty, skipped")
            continue
        start = dt.datetime.fromtimestamp(d.get("utc0", 0), dt.timezone(dt.timedelta(hours=1)))
        ax.plot(d["te"], (d["pwm"] - 1100) / 11, "k", lw=.6, label="pwm %")
        ax.plot(d["ta"], d["ias"], "g", lw=.6, label="IAS")
        ax.plot(d["tg"], d["gs"], "c", lw=.6, label="GPS")
        ax.plot(d["tf"], d["F"], "b", lw=.7, label="F N")
        ax.plot(d["t"], d["I"], "r", lw=.3, label="I A")
        ax.plot(d["t"], d["V"] * 4, "m", lw=.5, label="V*4")
        ax.set_ylim(-10, 110)
        ax.set_title(f"{os.path.basename(f)}  start {start:%H:%M:%S}  rho {d['rho']:.3f} T {d['temp']:.1f}C")
        ax.legend(loc="upper left", fontsize=6, ncol=6)
        ax.grid()
        print(os.path.basename(f), f"{start:%H:%M:%S}", f"dur {d['t'][-1]:.0f}s", f"Vmax {d['V'].max():.2f}",
              f"Imax {d['I'].max():.1f}", f"F {d['F'].min():.1f}..{d['F'].max():.1f}", f"IASmax {d['ias'].max():.1f}",
              f"GSmax {d['gs'].max():.1f}", f"pwm {d['pwm'].min():.0f}-{d['pwm'].max():.0f}", f"rho {d['rho']:.3f}")
    plt.tight_layout()
    plt.savefig(out, dpi=50)


# ---------------------------------------------------------------------------------------------
# Propeller coefficients and simulation on a common battery
# ---------------------------------------------------------------------------------------------
KV, R_DRIVE, I0, ESC = 985.0, 0.080, 1.4, 0.95       # GT2820/06 on the team rig (static + car fits)
PROPS = {  # session -> (label, diameter in, pitch in, folding)
    "036000_12x6_fija(arranque)": ("12x6", 12.0, 6.0, False),
    "036002_12x7_fija.ulg": ("12x7", 12.0, 7.0, False),
    "025001_12x7.5_fija.ulg": ("12x7.5", 12.0, 7.5, False),
    "037001_12x7.5_plegable.ulg": ("12x7.5 folding", 12.0, 7.5, True),
    "039001_12.5x7.5_fija.ulg": ("12.5x7.5", 12.5, 7.5, False),
    "040001_13x6.5_fija.ulg": ("13x6.5", 13.0, 6.5, False),
    "027001_11x7_fija.ulg": ("11x7", 11.0, 7.0, False),
    "042001_11x7_plegable.ulg": ("11x7 folding", 11.0, 7.0, True),
}


def coefficients(p, D_in):
    """J, CT, CP per sample. CP from the motor model: ESC input power x efficiency = (omega/Kv + I_m R) I_m."""
    m = np.isfinite(p["rpm"]) & (p["rpm"] > 3000)
    D = D_in * 0.0254
    n = p["rpm"][m] / 60
    w = 2 * np.pi * n
    kvs = KV * 2 * np.pi / 60
    P_in = p["V"][m] * p["I"][m] * ESC
    I_m = (-(w / kvs) + np.sqrt((w / kvs) ** 2 + 4 * R_DRIVE * P_in)) / (2 * R_DRIVE)
    Q = (I_m - I0) / kvs
    V = np.clip(p["tas"][m], 0, None)
    return dict(J=V / (n * D), CT=p["F"][m] / (p["rho"] * n ** 2 * D ** 4),
                CP=2 * np.pi * Q / (p["rho"] * n ** 2 * D ** 5), V=V, rpm=p["rpm"][m], t=p["t"][m])


def fit_poly(J, y, deg=2):
    """Robust quadratic fit (two passes, dropping >3 sigma outliers)."""
    c = np.polyfit(J, y, deg)
    r = y - np.polyval(c, J)
    keep = np.abs(r) < 3 * r.std()
    c = np.polyfit(J[keep], y[keep], deg)
    r = y[keep] - np.polyval(c, J[keep])
    return c, r.std()


def simulate(ct_c, cp_c, D_in, V_air, V_oc=12.2, IR=0.035, rho=1.20, j_max=None):
    """Full-throttle operating point at airspeed V_air on a common battery (open-circuit V_oc, resistance IR)."""
    from scipy.optimize import brentq
    D = D_in * 0.0254
    kvs = KV * 2 * np.pi / 60

    def torque_prop(w):
        n = w / (2 * np.pi)
        J = V_air / (n * D)
        if j_max is not None:
            J = min(J, j_max)
        return np.polyval(cp_c, J) * rho * n ** 2 * D ** 5 / (2 * np.pi)

    def res(w):
        I_m = I0 + torque_prop(w) * kvs
        return w / kvs + I_m * (R_DRIVE + IR / ESC) - V_oc

    w = brentq(res, 200, kvs * V_oc)
    n = w / (2 * np.pi)
    J = V_air / (n * D)
    T = np.polyval(ct_c, min(J, j_max) if j_max else J) * rho * n ** 2 * D ** 4
    I_m = I0 + torque_prop(w) * kvs
    I_b = I_m / ESC
    return dict(V=V_air, T=T, rpm=n * 60, J=J, I=I_b, P=(V_oc - IR * I_b) * I_b, P_shaft=torque_prop(w) * w)


ROC_REQ = 120.0 / 50.0        # m/s: 120 m in 60 s, leaving ~10 s for take-off run and transition
CLIMB_BAND = (10.0, 18.0)     # m/s: plausible climb speeds for this class of aircraft
G = 9.80665


def max_mass(curve, LD, roc=ROC_REQ, band=CLIMB_BAND):
    """Heaviest aircraft (kg) that still climbs at `roc` with this prop, assuming drag = W / (L/D)
    and the best climb speed inside `band`.  ROC = V (T - D) / W  ->  W = T / (roc / V + 1 / (L/D))."""
    V, T = curve
    m = (V >= band[0]) & (V <= band[1])
    W = T[m] / (roc / V[m] + 1.0 / LD)
    i = np.argmax(W)
    return W[i] / G, V[m][i]


def make_figures(fits, out_dir, V_oc=12.2, IR=0.035):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    INK, INK2, GRID, SURFACE, BAND = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb", "#ecebe7"
    PAL = ["#2a78d6", "#eb6834", "#1baf7a", "#8a5cd1", "#c99a06", "#d6457b", "#52514e", "#0f8a8a"]
    W_, H_, DPI = 13.33, 7.5, 150
    plt.rcParams.update({"font.size": 13, "axes.titlesize": 14, "axes.labelsize": 13,
                         "xtick.labelsize": 11, "ytick.labelsize": 11, "legend.fontsize": 12})
    os.makedirs(out_dir, exist_ok=True)

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
        fig, axes = plt.subplots(1, ncols, figsize=(W_, H_))
        fig.patch.set_facecolor(SURFACE)
        fig.text(0.015, 0.965, title, fontsize=22, color=INK, ha="left", va="top", weight="bold")
        fig.text(0.015, 0.905, subtitle, fontsize=13, color=INK2, ha="left", va="top")
        return fig, axes

    def save(fig, name):
        fig.tight_layout(rect=(0, 0.05, 1, 0.86))
        fig.savefig(os.path.join(out_dir, name), dpi=DPI, facecolor=SURFACE)
        plt.close(fig)
        print("wrote", name)

    Vs = np.arange(0, 30.01, 0.5)
    curves = {}
    for lab, (cc, cp, D, P, fold, jmax) in fits.items():
        S = [simulate(cc, cp, D, v, V_oc=V_oc, IR=IR) for v in Vs]
        curves[lab] = dict(T=np.array([s["T"] for s in S]), I=np.array([s["I"] for s in S]),
                           P=np.array([s["P"] for s in S]), rpm=np.array([s["rpm"] for s in S]))
    i13 = np.argmin(abs(Vs - 13))
    order = sorted(fits, key=lambda l: -curves[l]["T"][i13])
    color = {l: PAL[i] for i, l in enumerate(order)}
    src = (f"Car tests 12 & 14 Nov · GT2820/06 · all props on the same 3S2P battery "
           f"({V_oc} V open-circuit, {IR * 1000:.0f} mΩ) · ρ 1.20 kg/m³")

    # 1. full-throttle thrust vs airspeed
    fig, ax = figure("Full-throttle thrust vs. airspeed", src)
    style(ax)
    ax.axvspan(*CLIMB_BAND, color=BAND, zorder=0)
    ax.text(np.mean(CLIMB_BAND), 23.3, "climb speeds", ha="center", color=INK2, fontsize=12)
    ends = []
    for lab in order:
        c = curves[lab]
        ls = (0, (5, 3)) if fits[lab][4] else "-"
        ax.plot(Vs, c["T"], color=color[lab], linewidth=2.4, linestyle=ls)
        ends.append([c["T"][-1], lab])
    ends.sort()
    for k in range(1, len(ends)):                    # de-overlap the end labels
        ends[k][0] = max(ends[k][0], ends[k - 1][0] + 0.75)
    for y, lab in ends:
        ax.text(30.4, y, lab, color=color[lab], fontsize=12, weight="bold", va="center")
    ax.set_xlim(0, 34.5)
    ax.set_ylim(0, 24)
    ax.set_xlabel("True airspeed [m/s]", color=INK)
    ax.set_ylabel("Thrust [N]", color=INK)
    fig.text(0.015, 0.02, "Curves: measured C_T(J), C_P(J) of each prop + fitted motor; they reproduce the raw car data "
             "within 0.3–0.6 N rms. Dashed: folding props.", fontsize=11, color=INK2)
    save(fig, "10_car_thrust_vs_airspeed.png")

    # 2. climb ranking: thrust at 13 m/s and heaviest aircraft that makes 120 m in 60 s
    fig, (a1, a2) = figure("Which prop climbs best?",
                           f"Left: thrust at 13 m/s, a typical climb speed. Right: heaviest aircraft that still climbs at "
                           f"{ROC_REQ:.1f} m/s (120 m in ~50 s).", ncols=2)
    y = np.arange(len(order))[::-1]
    for ax in (a1, a2):
        style(ax)
        ax.grid(axis="y", visible=False)
        ax.set_yticks(y, order)
    t13 = [curves[l]["T"][i13] for l in order]
    a1.barh(y, t13, color=[color[l] for l in order], height=0.62)
    for yy, v, l in zip(y, t13, order):
        a1.text(v, yy, f" {v:.1f} N · {curves[l]['I'][i13]:.0f} A", va="center", color=INK, fontsize=11)
    a1.set_xlabel("Thrust at 13 m/s, full throttle [N]", color=INK)
    a1.set_xlim(0, 21)
    for LD, mk, txt in ((6, "o", "L/D 6"), (8, "D", "L/D 8"), (10, "s", "L/D 10")):
        mm = [max_mass((Vs, curves[l]["T"]), LD)[0] for l in order]
        a2.scatter(mm, y, marker=mk, s=70, color=[color[l] for l in order], edgecolor=SURFACE, zorder=3)
        a2.text(mm[0], y[0] + 0.45, txt, ha="center", color=INK2, fontsize=11)
    for yy, l in zip(y, order):
        lo = max_mass((Vs, curves[l]["T"]), 6)[0]
        hi = max_mass((Vs, curves[l]["T"]), 10)[0]
        a2.plot([lo, hi], [yy, yy], color=color[l], linewidth=2, zorder=2)
    a2.set_xlabel("Maximum take-off mass for 120 m in 60 s [kg]", color=INK)
    a2.set_ylim(-0.6, len(order) - 0.1)
    fig.text(0.015, 0.02, "Right: drag taken as weight ÷ (L/D) at the best climb speed between 10 and 18 m/s. "
             "Absolute values scale with the load-cell calibration; the ranking does not.", fontsize=11, color=INK2)
    save(fig, "11_car_climb_ranking.png")

    # 3. current and fixed vs folding
    fig, (a1, a2) = figure("Battery current and folding vs. fixed blades",
                           "Left: full-throttle battery current. Right: same size, fixed vs folding.", ncols=2)
    for ax in (a1, a2):
        style(ax)
    for lab in order:
        a1.plot(Vs, curves[lab]["I"], color=color[lab], linewidth=2.2,
                linestyle=(0, (5, 3)) if fits[lab][4] else "-")
    ends = sorted([[curves[l]["I"][0], l] for l in order])
    for k in range(1, len(ends)):
        ends[k][0] = max(ends[k][0], ends[k - 1][0] + 1.1)
    for yv, l in ends:
        a1.text(-0.5, yv, l, color=color[l], fontsize=11, weight="bold", va="center", ha="right")
    a1.set_xlim(-9, 30)
    a1.set_xticks([0, 10, 20, 30])
    a1.set_xlabel("True airspeed [m/s]", color=INK)
    a1.set_ylabel("Battery current [A]", color=INK)
    for pair in (("12x7.5", "12x7.5 folding"), ("11x7", "11x7 folding")):
        for lab in pair:
            a2.plot(Vs, curves[lab]["T"], color=color[lab], linewidth=2.4,
                    linestyle=(0, (5, 3)) if fits[lab][4] else "-", label=lab)
    a2.axvspan(*CLIMB_BAND, color=BAND, zorder=0)
    a2.legend(frameon=False)
    a2.set_xlabel("True airspeed [m/s]", color=INK)
    a2.set_ylabel("Thrust [N]", color=INK)
    a2.set_ylim(0, 23)
    save(fig, "12_car_current_folding.png")
    return curves, Vs


def run(root, out_dir=OUT):
    import csv
    import datetime as dt
    runs = {}
    for f in sorted(glob.glob(os.path.join(root, "*/sesion/*.ulg"))):
        n = os.path.basename(f)
        if n in PROPS:
            runs[n] = full_throttle_points(load(f))
    d = load(os.path.join(root, "2026-11-14/arranque/036000.ulg"))      # the 12x6 has no session log
    utc = lambda hh, mm: dt.datetime(2026, 11, 14, hh, mm, tzinfo=dt.timezone.utc).timestamp() - d["utc0"]
    runs["036000_12x6_fija(arranque)"] = full_throttle_points(d, (utc(10, 57), utc(11, 4)))
    fits = {}
    for k, (lab, D, P, fold) in PROPS.items():
        c = coefficients(runs[k], D)
        cc, _ = fit_poly(c["J"], c["CT"])
        cp, _ = fit_poly(c["J"], c["CP"])
        fits[lab] = (cc, cp, D, P, fold, c["J"].max())
    curves, Vs = make_figures(fits, out_dir)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "car_tests_summary.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["prop", "CT_static", "CP_static", "T_0", "T_10", "T_13", "T_15", "T_20", "I_0", "I_13",
                    "max_mass_kg_LD6", "max_mass_kg_LD8", "max_mass_kg_LD10", "best_climb_V_LD8"])
        for lab, (cc, cp, D, P, fold, jm) in fits.items():
            c = curves[lab]
            at = lambda v, key="T": float(np.interp(v, Vs, c[key]))
            mm = [max_mass((Vs, c["T"]), LD) for LD in (6, 8, 10)]
            w.writerow([lab, round(np.polyval(cc, 0), 4), round(np.polyval(cp, 0), 4)] +
                       [round(at(v), 2) for v in (0, 10, 13, 15, 20)] + [round(at(0, "I"), 1), round(at(13, "I"), 1)] +
                       [round(x[0], 2) for x in mm] + [mm[1][1]])
    return fits, curves


if __name__ == "__main__" and len(sys.argv) == 2:
    run(sys.argv[1])
