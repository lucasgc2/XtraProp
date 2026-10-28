"""Before/after comparison of the Aero-naut CAM presets against all UIUC Volume 3 data.

before - presets as they were: constant 2 cm chord, constant pitch, MH114 -> MH116 (Ncrit 9),
         drag held constant below the lowest polar Reynolds number
after  - fitted presets now in presets.json (Clark Y Ncrit 5, low-Re drag scaling)

Run:  python compare_aeronaut.py     -> results/aeronaut_summary.csv, results/aeronaut_curves.png
"""
import csv
import math
import os
import subprocess

import numpy as np
import json

import fit_aeronaut as fa
import plots

m = fa.m
CODES = {"10x6": "10 x 6", "12x6": "12 x 6", "125x75": "12.5 x 7.5", "13x8": "13 x 8",
         "14x6": "14 x 6", "14x8": "14 x 8"}


def old_presets():
    txt = subprocess.run(["git", "show", "24ca479:XtraProp/presets.json"], cwd=fa.HERE,
                         capture_output=True, text=True, check=True).stdout
    return json.loads(txt)["propellers"]


def evaluate(preset, code, low_re_exponent):
    m.LOW_RE_DRAG_EXPONENT = low_re_exponent
    prop = m.from_preset(m.Propeller, preset)
    af = m.prop_airfoil(prop)
    static, runs = fa.load(code)
    st = static[static[:, 0] >= 1900]
    s = np.array([fa.coeffs(prop, af, rpm, 0.0) for rpm in st[:, 0]])
    ct_n, cp_n, curves = [], [], {}
    for rpm, d in runs.items():
        ct_ref = np.interp(rpm, static[:, 0], static[:, 1])
        cp_ref = np.interp(rpm, static[:, 0], static[:, 2])
        mod = np.array([fa.coeffs(prop, af, rpm, J) for J in d[:, 0]])
        ct_n += list((mod[:, 0] - d[:, 1]) / ct_ref)
        cp_n += list((mod[:, 1] - d[:, 2]) / cp_ref)
        Jf = np.linspace(0, d[:, 0].max() + 0.03, 36)
        curves[rpm] = dict(meas=d, Jf=Jf, model=np.array([fa.coeffs(prop, af, rpm, J) for J in Jf]))
    m.LOW_RE_DRAG_EXPONENT = -0.5
    return dict(static_CT_err_pct=100 * float(np.mean(s[:, 0] / st[:, 1] - 1)),
                static_CP_err_pct=100 * float(np.mean(s[:, 1] / st[:, 2] - 1)),
                curve_CT_rms_pct=100 * math.sqrt(np.mean(np.square(ct_n))),
                curve_CP_rms_pct=100 * math.sqrt(np.mean(np.square(cp_n)))), curves


if __name__ == "__main__":
    old = old_presets()
    new = json.load(open(os.path.join(os.path.dirname(fa.HERE), "XtraProp", "presets.json"), encoding="utf-8"))["propellers"]
    summary, curves = [], {}
    for code, short in CODES.items():
        name = f"{short} Aeronaut CAM Carbon"
        for cfg, preset, exp in (("before", old[name], 0.0), ("after", new[name], -0.5)):
            r, c = evaluate(preset, code, exp)
            summary.append(dict(prop=code, config=cfg, **r))
            curves[(code, cfg)] = dict(runs=c)
            print(f"{short:10s} {cfg:6s} static CT {r['static_CT_err_pct']:+6.1f}%  CP {r['static_CP_err_pct']:+6.1f}%"
                  f" | curve CT {r['curve_CT_rms_pct']:5.1f}%  CP {r['curve_CP_rms_pct']:5.1f}%", flush=True)
    print("\nAverage absolute error over the 6 props:")
    for cfg in ("before", "after"):
        rows = [r for r in summary if r["config"] == cfg]
        print(f"  {cfg:6s} " + "  ".join(f"{k} {np.mean([abs(r[k]) for r in rows]):.1f}%" for k in
                                          ("static_CT_err_pct", "static_CP_err_pct", "curve_CT_rms_pct", "curve_CP_rms_pct")))
    with open(os.path.join(fa.OUT, "aeronaut_summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0]))
        w.writeheader()
        w.writerows(summary)

    # plot: one column per prop, lowest-rpm run (widest J range)
    import matplotlib.pyplot as plt
    labels = {"before": "Before: 2 cm constant chord, MH114 -> MH116", "after": "After: fitted blade (shipped)"}
    colors = {"before": plots.SERIES[0], "after": plots.SERIES[2]}
    fig, axes = plt.subplots(3, len(CODES), figsize=(3.2 * len(CODES), 8.2), sharex="col")
    fig.patch.set_facecolor(plots.SURFACE)
    for col, (code, short) in enumerate(CODES.items()):
        runs = curves[(code, "after")]["runs"]
        full = [r for r in runs if runs[r]["meas"][0, 0] < 0.2]   # runs that start near static
        rpm = min(full, key=lambda r: abs(r - 4000))
        for row, (idx, ylab) in enumerate(((0, "$C_T$"), (1, "$C_P$"), (None, "Efficiency η"))):
            ax = axes[row, col]
            plots._style(ax)
            for cfg in ("before", "after"):
                c = curves[(code, cfg)]["runs"][rpm]
                Jf, mod = c["Jf"], c["model"]
                y = (np.where((mod[:, 0] > 0.002) & (mod[:, 1] > 0), Jf * mod[:, 0] / mod[:, 1], np.nan)
                     if idx is None else mod[:, idx])
                ax.plot(Jf, y, color=colors[cfg], linewidth=2, label=labels[cfg])
            d = curves[(code, "after")]["runs"][rpm]["meas"]
            y = np.where(d[:, 1] > 0.002, d[:, 3], np.nan) if idx is None else d[:, idx + 1]
            ax.plot(d[:, 0], y, "o", color=plots.INK, markersize=4.5, markeredgecolor=plots.SURFACE,
                    markeredgewidth=0.8, label="UIUC wind tunnel", zorder=5)
            if idx is None:
                ax.set_ylim(0, 0.9)
            else:
                ax.axhline(0, color=plots.INK2, linewidth=0.8)
            if col == 0:
                ax.set_ylabel(ylab, color=plots.INK, fontsize=10)
            if row == 0:
                ax.set_title(f"CAM {short}  ·  {rpm} rpm", color=plots.INK, fontsize=10)
            if row == 2:
                ax.set_xlabel("Advance ratio J", color=plots.INK2, fontsize=9)
    h, l = axes[0, 0].get_legend_handles_labels()
    order = [l.index("UIUC wind tunnel")] + [i for i, x in enumerate(l) if x != "UIUC wind tunnel"]
    fig.legend([h[i] for i in order], [l[i] for i in order], loc="lower center", ncol=3, frameon=False,
               fontsize=9, labelcolor=plots.INK)
    fig.suptitle("Aero-naut CAM folding props: XtraProp vs. UIUC wind-tunnel data", color=plots.INK,
                 fontsize=12, x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0.04, 1, 0.97))
    fig.savefig(os.path.join(fa.OUT, "aeronaut_curves.png"), dpi=150, facecolor=plots.SURFACE)
    print("Plot written")
