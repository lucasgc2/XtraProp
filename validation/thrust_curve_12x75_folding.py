"""Thrust curve of the folding 12x7.5 prop from the car tests (14 Nov 2026).

Left:  full-throttle thrust vs airspeed (fixed 12x7.5 shown for comparison)
Right: full-throttle battery current vs airspeed, against the 50 A limit
(No static throttle curve: the folding prop was not on the October stand, and its only stationary
throttle ramp in the car run lasted ~3 s, too fast for the 11 Hz load cell.)

Run:  python thrust_curve_12x75_folding.py <car-test folder> [es]
      -> results/car_tests/14_thrust_curve_12x7.5_folding[_es].png
"""
import os
import sys

import numpy as np

import car_tests as ct

I_LIMIT = 50.0


def main(car_root, lang="en"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    es = lang == "es"
    tr = lambda en, sp: sp if es else en
    num = lambda v, nd=1: (f"{v:.{nd}f}".replace(".", ",") if es else f"{v:.{nd}f}")
    INK, INK2, GRID, SURFACE, BAND = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb", "#ecebe7"
    BLUE, GREEN, GREY, RED = "#2a78d6", "#1baf7a", "#a3a19b", "#d03b3b"
    plt.rcParams.update({"font.size": 13, "axes.labelsize": 13, "xtick.labelsize": 11,
                         "ytick.labelsize": 11, "legend.fontsize": 11.5})

    runs = {}
    for key, rel in (("folding", "2026-11-14/sesion/037001_12x7.5_plegable.ulg"),
                     ("fixed", "2026-11-12/sesion/025001_12x7.5_fija.ulg")):
        runs[key] = ct.full_throttle_points(ct.load(os.path.join(car_root, rel)))
    fits = {}
    for key, p in runs.items():
        c = ct.coefficients(p, 12.0)
        fits[key] = (ct.fit_poly(c["J"], c["CT"])[0], ct.fit_poly(c["J"], c["CP"])[0])
    Vs = np.arange(0, 30.01, 0.5)
    IR = 0.035
    p = runs["folding"]
    m = np.isfinite(p["rpm"])
    V_test = float(np.median(p["V"][m] + IR * p["I"][m]))
    sim = lambda key, voc: [ct.simulate(*fits[key], 12.0, v, V_oc=voc, IR=IR) for v in Vs]
    S_test, S_full, S_fixed = sim("folding", V_test), sim("folding", 12.2), sim("fixed", 12.2)
    T = lambda S: np.array([s["T"] for s in S])
    I = lambda S: np.array([s["I"] for s in S])
    errT, errI = [], []
    for v in range(0, 31, 3):
        b = m & (np.abs(np.clip(p["tas"], 0, None) - v) < 1.5)
        if b.sum() >= 15:
            errT.append(np.interp(v, Vs, T(S_test)) - np.median(p["F"][b]))
            errI.append(np.interp(v, Vs, I(S_test)) - np.median(p["I"][b]))
    rmsT = float(np.sqrt(np.mean(np.square(errT))))
    rmsI = float(np.sqrt(np.mean(np.square(errI))))

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13.33, 7.5), gridspec_kw=dict(width_ratios=[1.35, 1]))
    fig.patch.set_facecolor(SURFACE)
    fig.text(0.015, 0.965, tr("Folding 12x7.5 propeller: thrust curve", "Hélice plegable 12x7.5: curva de empuje"),
             fontsize=22, color=INK, ha="left", va="top", weight="bold")
    fig.text(0.015, 0.905, tr("Car tests, 14 Nov, EMAX GT2820/06 on 3S2P, full throttle. "
                              "Left: thrust. Right: battery current.",
                              "Ensayos en coche, 14 nov, EMAX GT2820/06 en 3S2P, gas máximo. "
                              "Izquierda: empuje. Derecha: corriente de batería."),
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
        ax.axvspan(10, 15, color=BAND, zorder=0)
        ax.set_xlim(0, 31)
        ax.set_xlabel(tr("True airspeed [m/s]", "Velocidad verdadera [m/s]"), color=INK)

    # left: thrust
    a1.text(12.5, 23.2, tr("climb speeds", "velocidades de subida"), ha="center", color=INK2, fontsize=11)
    a1.plot(np.clip(p["tas"], 0, None), p["F"], "o", color=GREY, markersize=2.5, alpha=0.4,
            label=tr(f"Measured (pack at ≈{V_test:.1f} V)", f"Medido (batería a ≈{num(V_test)} V)"))
    a1.plot(Vs, T(S_full), color=GREEN, linewidth=3,
            label=tr("Folding, charged 3S2P pack (12.2 V)", "Plegable, batería 3S2P cargada (12,2 V)"))
    a1.plot(Vs, T(S_fixed), color=BLUE, linewidth=1.8, linestyle=(0, (6, 3)), alpha=0.8,
            label=tr("Fixed 12x7.5, same pack (for comparison)", "Fija 12x7.5, misma batería (comparación)"))
    for v in (0, 10, 15):
        t = float(np.interp(v, Vs, T(S_full)))
        a1.annotate(f"{num(t)} N", (v, t), xytext=(8, 14), textcoords="offset points", color=GREEN,
                    fontsize=12, weight="bold", bbox=dict(boxstyle="round,pad=0.2", fc=SURFACE, ec="none", alpha=0.9))
        a1.plot(v, t, "o", color=GREEN, markersize=6, markeredgecolor=SURFACE)
    a1.set_ylim(0, 24)
    a1.set_ylabel(tr("Thrust at full throttle [N]", "Empuje a gas máximo [N]"), color=INK)
    a1.legend(frameon=False, loc="lower left")

    # right: current
    a2.plot(np.clip(p["tas"], 0, None), p["I"], "o", color=GREY, markersize=2.5, alpha=0.4,
            label=tr("Measured", "Medido"))
    a2.plot(Vs, I(S_full), color=GREEN, linewidth=3, label=tr("Charged pack (12.2 V)", "Batería cargada (12,2 V)"))
    a2.axhline(I_LIMIT, color=RED, linewidth=1.5, linestyle=(0, (5, 3)))
    a2.text(30.5, I_LIMIT + 0.6, tr(f"{I_LIMIT:.0f} A limit", f"límite {I_LIMIT:.0f} A"), color=RED,
            ha="right", fontsize=11.5)
    imax = float(I(S_full).max())
    a2.annotate(tr(f"max {imax:.0f} A", f"máx. {imax:.0f} A"), (Vs[np.argmax(I(S_full))], imax),
                xytext=(0, 24), textcoords="offset points", ha="center", color=GREEN, fontsize=12, weight="bold",
                bbox=dict(boxstyle="round,pad=0.2", fc=SURFACE, ec="none", alpha=0.9))
    a2.set_ylim(0, 55)
    a2.set_ylabel(tr("Battery current at full throttle [A]", "Corriente de batería a gas máximo [A]"), color=INK)
    a2.legend(frameon=False, loc="lower left")

    fig.text(0.015, 0.02, tr(f"Curves: the prop's measured coefficients + fitted motor; they match the car data within "
                             f"{rmsT:.1f} N and {rmsI:.1f} A rms.\nThrust is corrected for the stand's own drag. The "
                             f"load-cell scale is uncalibrated (may read ~10–15% high).",
                             f"Curvas: coeficientes medidos de la hélice + motor ajustado; coinciden con los datos del "
                             f"coche con {num(rmsT)} N y {num(rmsI)} A rms.\nEmpuje corregido por la resistencia del "
                             f"banco. La célula de carga no está calibrada (puede leer ~10–15% de más)."),
             fontsize=10.5, color=INK2)
    fig.tight_layout(rect=(0, 0.07, 1, 0.86))
    out = os.path.join(ct.OUT, "14_thrust_curve_12x7.5_folding" + ("_es" if es else "") + ".png")
    os.makedirs(ct.OUT, exist_ok=True)
    fig.savefig(out, dpi=150, facecolor=SURFACE)
    print("wrote", out, f"| pack {V_test:.2f} V, rms {rmsT:.2f} N {rmsI:.2f} A",
          "| T(0,10,13,15,20) =", [round(float(np.interp(v, Vs, T(S_full))), 1) for v in (0, 10, 13, 15, 20)],
          f"| Imax {imax:.1f} A")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "en")
