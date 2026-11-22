"""Thrust curves of the 12x7.5 prop from the team's own tests.

Left:  full-throttle thrust vs airspeed (car tests, 12 & 14 Nov 2026)
Right: static thrust vs throttle (thrust stand, October 2026)

Run:  python thrust_curve_12x75.py <car-test folder> <static 12x7.5 .ulg> [es]
      -> results/car_tests/13_thrust_curve_12x7.5[_es].png
"""
import os
import sys

import numpy as np

import car_tests as ct
import static_tests as st


def main(car_root, static_log, lang="en"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    es = lang == "es"
    tr = lambda en, sp: sp if es else en
    num = lambda v, nd=1: (f"{v:.{nd}f}".replace(".", ",") if es else f"{v:.{nd}f}")
    INK, INK2, GRID, SURFACE, BAND = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb", "#ecebe7"
    BLUE, ORANGE, GREEN, GREY = "#2a78d6", "#eb6834", "#1baf7a", "#a3a19b"
    plt.rcParams.update({"font.size": 13, "axes.labelsize": 13, "xtick.labelsize": 11,
                         "ytick.labelsize": 11, "legend.fontsize": 11.5})

    # --- car tests: fixed 12x7.5 (12 Nov) and folding 12x7.5 (14 Nov) ---
    runs = {}
    for key, rel in (("fixed", "2026-11-12/sesion/025001_12x7.5_fija.ulg"),
                     ("folding", "2026-11-14/sesion/037001_12x7.5_plegable.ulg")):
        runs[key] = ct.full_throttle_points(ct.load(os.path.join(car_root, rel)))
    fits = {}
    for key, p in runs.items():
        c = ct.coefficients(p, 12.0)
        fits[key] = (ct.fit_poly(c["J"], c["CT"])[0], ct.fit_poly(c["J"], c["CP"])[0])
    Vs = np.arange(0, 30.01, 0.5)
    p = runs["fixed"]
    IR = 0.035
    m = np.isfinite(p["rpm"])
    V_test = float(np.median(p["V"][m] + IR * p["I"][m]))          # the fixed prop's (tired) pack that day
    curve = lambda key, voc: np.array([ct.simulate(*fits[key], 12.0, v, V_oc=voc, IR=IR)["T"] for v in Vs])
    T_test, T_full, T_fold = curve("fixed", V_test), curve("fixed", 12.2), curve("folding", 12.2)
    err = []
    for v in range(0, 31, 3):
        b = m & (np.abs(np.clip(p["tas"], 0, None) - v) < 1.5)
        if b.sum() >= 15:
            err.append(np.interp(v, Vs, T_test) - np.median(p["F"][b]))
    rms = float(np.sqrt(np.mean(np.square(err))))

    # --- static test (October) ---
    full, ramp, d = st.analyse(static_log)

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13.33, 7.5), gridspec_kw=dict(width_ratios=[1.35, 1]))
    fig.patch.set_facecolor(SURFACE)
    fig.text(0.015, 0.965, tr("12x7.5 propeller: thrust curves", "Hélice 12x7.5: curvas de empuje"),
             fontsize=22, color=INK, ha="left", va="top", weight="bold")
    fig.text(0.015, 0.905, tr("Team tests with the EMAX GT2820/06 on 3S. Left: full throttle in forward flight "
                              "(car tests, Nov). Right: static thrust stand (Oct).",
                              "Ensayos del equipo con el EMAX GT2820/06 en 3S. Izquierda: gas máximo en vuelo "
                              "(ensayos en coche, nov). Derecha: banco estático (oct)."),
             fontsize=13, color=INK2, ha="left", va="top")
    comma = FuncFormatter(lambda x, _: f"{x:g}".replace(".", ","))
    for ax in (a1, a2):
        ax.set_facecolor(SURFACE)
        ax.grid(True, color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color(INK2)
        ax.tick_params(colors=INK2)
        if es:
            ax.xaxis.set_major_formatter(comma)
            ax.yaxis.set_major_formatter(comma)

    # left panel
    a1.axvspan(10, 15, color=BAND, zorder=0)
    a1.text(12.5, 23.2, tr("climb speeds", "velocidades de subida"), ha="center", color=INK2, fontsize=11)
    a1.plot(np.clip(p["tas"], 0, None), p["F"], "o", color=GREY, markersize=2.5, alpha=0.45,
            label=tr(f"Measured, fixed prop (pack at ≈{V_test:.1f} V)", f"Medido, hélice fija (batería a ≈{num(V_test)} V)"))
    a1.plot(Vs, T_test, color=BLUE, linewidth=2, linestyle=(0, (4, 3)),
            label=tr("Fit to the measurements", "Ajuste a las medidas"))
    a1.plot(Vs, T_full, color=BLUE, linewidth=3,
            label=tr("Fixed, charged 3S2P pack (12.2 V)", "Fija, batería 3S2P cargada (12,2 V)"))
    a1.plot(Vs, T_fold, color=GREEN, linewidth=2.2, linestyle=(0, (6, 3)),
            label=tr("Folding, same pack (12.2 V)", "Plegable, misma batería (12,2 V)"))
    for v in (0, 10, 15):
        t = float(np.interp(v, Vs, T_full))
        a1.annotate(f"{num(t)} N", (v, t), xytext=(6, 6), textcoords="offset points", color=BLUE,
                    fontsize=11.5, weight="bold")
        a1.plot(v, t, "o", color=BLUE, markersize=6, markeredgecolor=SURFACE)
    a1.set_xlim(0, 31)
    a1.set_ylim(0, 24)
    a1.set_xlabel(tr("True airspeed [m/s]", "Velocidad verdadera [m/s]"), color=INK)
    a1.set_ylabel(tr("Thrust at full throttle [N]", "Empuje a gas máximo [N]"), color=INK)
    a1.legend(frameon=False, loc="lower left")

    # right panel: static thrust vs throttle
    thr, F = ramp["thr"], ramp["F"]
    a2.plot(thr, F, "o", color=ORANGE, markersize=3, alpha=0.6, label=tr("Throttle ramp", "Rampa de gas"))
    a2.plot(100, full["F"], "o", color=ORANGE, markersize=11, markeredgecolor=SURFACE, markeredgewidth=1.5,
            label=tr("Full-throttle hold (mean)", "Gas máximo mantenido (media)"))
    a2.annotate(f"{num(full['F'])} N\n{full['I']:.0f} A · {full['P']:.0f} W\n{full['rpm']:.0f} rpm",
                (100, full["F"]), xytext=(0.97, 0.30), textcoords="axes fraction", ha="right", va="center", color=INK,
                fontsize=11.5, arrowprops=dict(arrowstyle="-", color=INK2, linewidth=0.8))
    a2.set_xlim(0, 105)
    a2.set_ylim(0, 24)
    a2.set_xlabel(tr("Throttle [%]", "Gas [%]"), color=INK)
    a2.set_ylabel(tr("Static thrust [N]", "Empuje estático [N]"), color=INK)
    a2.legend(frameon=False, loc="upper left")

    fig.text(0.015, 0.02, tr(f"Left curves: the prop's measured coefficients + fitted motor; they match the car data within "
                             f"{rms:.1f} N rms.\nThrust is corrected for the stand's own drag. The load-cell scale is "
                             f"uncalibrated (may read ~10–15% high).",
                             f"Curvas de la izquierda: coeficientes medidos de la hélice + motor ajustado; coinciden con los "
                             f"datos del coche con {num(rms)} N rms.\nEmpuje corregido por la resistencia del banco. La célula "
                             f"de carga no está calibrada (puede leer ~10–15% de más)."),
             fontsize=10.5, color=INK2)
    fig.tight_layout(rect=(0, 0.07, 1, 0.86))
    out = os.path.join(ct.OUT, "13_thrust_curve_12x7.5" + ("_es" if es else "") + ".png")
    os.makedirs(ct.OUT, exist_ok=True)
    fig.savefig(out, dpi=150, facecolor=SURFACE)
    print("wrote", out, f"| test pack {V_test:.2f} V, fit rms {rms:.2f} N",
          "| T(0,10,13,15,20) =", [round(float(np.interp(v, Vs, T_full)), 1) for v in (0, 10, 13, 15, 20)],
          "| static", round(full["F"], 2), "N")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "en")
