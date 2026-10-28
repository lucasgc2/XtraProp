"""Slide-ready figures (16:9) comparing XtraProp with experimental data.

Writes results/presentation/01..05_*.png. Run from this folder:  python presentation_figures.py
"""
import csv
import json
import math
import os
import subprocess

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import fit_aeronaut as fa
import tyto_check
import validate
import build_apc_presets as apc
import compare_aeronaut as ca

m = fa.m
OUT = os.path.join(fa.OUT, "presentation")
INK, INK2, GRID, SURFACE, BAND = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb", "#ecebe7"
BEFORE, AFTER, ACCENT = "#a3a19b", "#2a78d6", "#eb6834"
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


def figure(title, subtitle, nrows=1, ncols=1, **kw):
    fig, axes = plt.subplots(nrows, ncols, figsize=(W, H), **kw)
    fig.patch.set_facecolor(SURFACE)
    fig.text(0.015, 0.965, title, fontsize=22, color=INK, ha="left", va="top", weight="bold")
    fig.text(0.015, 0.905, subtitle, fontsize=13, color=INK2, ha="left", va="top")
    return fig, axes


def save(fig, name, rect=(0, 0.06, 1, 0.86)):
    fig.tight_layout(rect=rect)
    os.makedirs(OUT, exist_ok=True)
    fig.savefig(os.path.join(OUT, name), dpi=DPI, facecolor=SURFACE)
    plt.close(fig)
    print("wrote", name)


def read_summary(path):
    with open(path) as f:
        return list(csv.DictReader(f))


# ------------------------------------------------------------------ 1. accuracy summary

def fig_summary():
    apc_rows = read_summary(os.path.join(fa.OUT, "summary.csv"))
    an_rows = read_summary(os.path.join(fa.OUT, "aeronaut_summary.csv"))
    metrics = [("static_CT_err_pct", "Static\nthrust"), ("static_CP_err_pct", "Static\npower"),
               ("curve_CT_rms_pct", "Thrust vs\nairspeed"), ("curve_CP_rms_pct", "Power vs\nairspeed")]
    fig, axes = figure("Propeller model accuracy: before vs. after",
                       "Average error against UIUC wind-tunnel measurements (lower is better)", 1, 2, sharey=True)
    for ax, rows, title in ((axes[0], apc_rows, "APC Thin Electric (5 props)"),
                            (axes[1], an_rows, "Aero-naut CAM Carbon folding (6 props)")):
        style(ax)
        x = np.arange(len(metrics))
        for i, (cfg, color, lab) in enumerate((("before", BEFORE, "Before"), ("after", AFTER, "After"))):
            vals = [np.mean([abs(float(r[k])) for r in rows if r["config"] == cfg]) for k, _ in metrics]
            bars = ax.bar(x + (i - 0.5) * 0.36, vals, 0.34, color=color, label=lab, zorder=3)
            for b, v in zip(bars, vals):
                ax.text(b.get_x() + b.get_width() / 2, v + 0.4, f"{v:.1f}%", ha="center", va="bottom",
                        fontsize=11, color=INK)
        ax.set_xticks(x, [l for _, l in metrics], color=INK)
        ax.set_title(title, color=INK, loc="left", fontsize=15)
    axes[0].set_ylabel("Average error (%)", color=INK)
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=2, frameon=False, labelcolor=INK)
    save(fig, "01_accuracy_summary.png")


# ------------------------------------------------------------------ 2/3. coefficient curves

def curves_fig(name, title, subtitle, panels, show_before=True):
    """panels: list of (label, rpm, meas array [J CT CP eta], before (Jf, mod), after (Jf, mod))"""
    fig, axes = figure(title, subtitle, 2, len(panels), sharex="col")
    for col, (lab, rpm, d, before, after) in enumerate(panels):
        for row, (idx, ylab) in enumerate(((0, "Thrust coefficient $C_T$"), (1, "Power coefficient $C_P$"))):
            ax = axes[row, col]
            style(ax)
            if show_before:
                ax.plot(before[0], before[1][:, idx], color=BEFORE, linewidth=2.2, linestyle="--", label="Before")
            ax.plot(after[0], after[1][:, idx], color=AFTER, linewidth=2.6, label="After (shipped model)")
            ax.plot(d[:, 0], d[:, idx + 1], "o", color=INK, markersize=5.5, markeredgecolor=SURFACE,
                    markeredgewidth=0.8, label="Wind-tunnel measurement", zorder=5)
            ax.axhline(0, color=INK2, linewidth=0.8)
            if col == 0:
                ax.set_ylabel(ylab, color=INK)
            if row == 0:
                ax.set_title(f"{lab}\n{rpm} rpm", color=INK, fontsize=13)
            else:
                ax.set_xlabel("Advance ratio J", color=INK2, fontsize=11)
    h, l = axes[0, 0].get_legend_handles_labels()
    order = [l.index("Wind-tunnel measurement")] + [i for i, x in enumerate(l) if x != "Wind-tunnel measurement"]
    fig.legend([h[i] for i in order], [l[i] for i in order], loc="lower center", ncol=3, frameon=False,
               labelcolor=INK)
    save(fig, name)


def fig_apc_curves():
    _, curves = validate.run()
    panels = []
    for p in validate.PROPS:
        runs = curves[(p, "after")]["runs"]
        rpm = min(runs)
        d = runs[rpm]["meas"]
        b = curves[(p, "before")]["runs"][rpm]
        a = runs[rpm]
        panels.append((f"APC {p}E", rpm, d, (b["Jf"], b["model"]), (a["Jf"], a["model"])))
    curves_fig("02_apc_vs_wind_tunnel.png", "APC Thin Electric props vs. wind-tunnel data",
               "Blade shape from APC's published geometry files · J = airspeed / (rev/s × diameter) · data: UIUC Propeller Database, Vol. 1", panels)


def fig_aeronaut_curves():
    old = ca.old_presets()
    new = json.load(open(os.path.join(os.path.dirname(fa.HERE), "XtraProp", "presets.json"), encoding="utf-8"))["propellers"]
    panels = []
    for code, short in ca.CODES.items():
        name = f"{short} Aeronaut CAM Carbon"
        _, cb = ca.evaluate(old[name], code, 0.0)
        _, cn = ca.evaluate(new[name], code, -0.5)
        full = [r for r in cn if cn[r]["meas"][0, 0] < 0.2]
        rpm = min(full, key=lambda r: abs(r - 4000))
        panels.append((f"CAM {short}", rpm, cn[rpm]["meas"], (cb[rpm]["Jf"], cb[rpm]["model"]),
                       (cn[rpm]["Jf"], cn[rpm]["model"])))
    curves_fig("03_aeronaut_vs_wind_tunnel.png", "Aero-naut CAM Carbon folding props vs. wind-tunnel data",
               "Blade shape fitted to the measurements (highest-rpm runs held out) · J = airspeed / (rev/s × diameter) · data: UIUC Vol. 3",
               panels)


# ------------------------------------------------------------------ 4. full system test

def fig_system():
    new = json.load(open(os.path.join(os.path.dirname(fa.HERE), "XtraProp", "presets.json"), encoding="utf-8"))["propellers"]
    old = ca.old_presets()
    rows_a, _, _ = tyto_check.run(new["10 x 6 Aeronaut CAM Carbon"], verbose=False)
    rows_b, _, _ = tyto_check.run(old["10 x 6 Aeronaut CAM Carbon"], verbose=False)
    fig, axes = figure("Full system test: motor + ESC + propeller on a thrust stand",
                       "Hacker A30-14L V4 (800 kv) + Aero-naut CAM Carbon Z 10×6, ~16 V, static · "
                       "data: Tyto Robotics test database (test 9grq)", 1, 3)
    specs = [("Q", "Shaft torque (N·m)", 1), ("I", "Battery current (A)", 1), ("T", "Thrust (N)", 1)]
    for ax, (k, lab, _) in zip(axes, specs):
        style(ax)
        rpm = [r["rpm"] for r in rows_a]
        ax.plot([r["rpm"] for r in rows_b], [r[f"{k}_model"] for r in rows_b], color=BEFORE, linewidth=2.2,
                linestyle="--", label="Before")
        ax.plot(rpm, [r[f"{k}_model"] for r in rows_a], color=AFTER, linewidth=2.6, label="After (shipped model)")
        ax.plot(rpm, [r[f"{k}_meas"] for r in rows_a], "o", color=INK, markersize=6, markeredgecolor=SURFACE,
                markeredgewidth=0.8, label="Thrust-stand measurement", zorder=5)
        err = 100 * np.mean([r[f"{k}_model"] / r[f"{k}_meas"] - 1 for r in rows_a if r["rpm"] > 7000])
        errb = 100 * np.mean([r[f"{k}_model"] / r[f"{k}_meas"] - 1 for r in rows_b if r["rpm"] > 7000])
        ax.set_title(lab, color=INK, loc="left")
        ax.text(0.03, 0.95, f"After: {err:+.1f}%\nBefore: {errb:+.0f}%", transform=ax.transAxes, va="top",
                fontsize=12, color=INK, bbox=dict(boxstyle="round,pad=0.4", fc="white", ec=GRID))
        ax.set_xlabel("rpm", color=INK2)
    fig.text(0.015, 0.075, "Errors: averages above 7,000 rpm.  Torque is the direct test of the prop model.  "
             "Thrust: this stand reads ~21% less than the UIUC wind tunnel at the same power,\nso most of the gap "
             "is the test setup.  Current: predicted high with datasheet motor constants (safe side); "
             "1.5–5% error once the motor is calibrated with fit_motor.py.",
             fontsize=10.5, color=INK2, ha="left", va="bottom")
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=3, frameon=False, labelcolor=INK, bbox_to_anchor=(0.5, 0.0))
    save(fig, "04_system_test_hacker_cam10x6.png", rect=(0, 0.12, 1, 0.86))


# ------------------------------------------------------------------ 5. GT2820/06 data point

def fig_gt2820():
    presets = json.load(open(os.path.join(os.path.dirname(fa.HERE), "XtraProp", "presets.json"), encoding="utf-8"))
    mot = m.from_preset(m.Motor, presets["motors"]["XtraChallenge 2027 - EMAX GT2820/06"])
    p = m.from_preset(m.Propeller, apc.apc_preset("12x6E", "APC 12x6E"))
    af = m.prop_airfoil(p)
    atm = m.atmosphere_from(0, 20)
    volts = np.linspace(13.5, 16.0, 11)
    P, I, T = [], [], []
    for v in volts:
        bat = m.Battery(name="4S", cells=4, nominal_voltage=14.8, max_voltage=v, capacity_mah=2200,
                        discharge_c=40, internal_resistance=0.0)
        pt = m.motor_battery(p, af, mot, bat, 1.0, 0.0, atm)       # app default ESC efficiency (95%)
        P.append(v * pt.I_battery)
        I.append(pt.I_battery)
        T.append(pt.thrust / 9.80665)
    fig, ax = figure("Same motor: EMAX GT2820/06 + 12×6 on 4S, full throttle",
                     "The only published measurement of this motor: 836 W input power (RCFlight.se) · "
                     "prop assumed to be the APC 12×6E recommended for it")
    style(ax)
    ax.fill_between(volts, np.array(P) * 0.9, np.array(P) * 1.1, color=AFTER, alpha=0.12, linewidth=0,
                    label="Model ±10%")
    ax.plot(volts, P, color=AFTER, linewidth=2.8, label="Model: input power vs. battery voltage under load")
    ax.axhline(836, color=ACCENT, linewidth=2.4, linestyle="--", label="Measured: 836 W")
    v_match = float(np.interp(836, P, volts))
    ax.plot([v_match], [836], "o", color=INK, markersize=9, zorder=5)
    ax.annotate(f"Model matches 836 W at {v_match:.1f} V under load\n(~3.6 V per cell, typical for a 4S pack at ~58 A)",
                xy=(v_match, 836), xytext=(13.6, 960), fontsize=12, color=INK,
                arrowprops=dict(arrowstyle="->", color=INK2))
    ax.set_xlabel("Battery voltage under load (V)", color=INK)
    ax.set_ylabel("Electrical input power (W)", color=INK)
    ax.set_ylim(600, 1100)
    ax.axvspan(14.0, 15.2, color=BAND, zorder=0)
    ax.text(14.6, 615, "typical loaded 4S range", ha="center", fontsize=11, color=INK2)
    fig.text(0.015, 0.075, "One data point with an unknown battery voltage can only check consistency, not "
             "calibrate the motor.\nA 10-minute wattmeter + tachometer test (README → Calibrating a motor) "
             "would give a full same-motor comparison.", fontsize=10.5, color=INK2, ha="left", va="bottom")
    ax.legend(loc="upper left", frameon=False, labelcolor=INK)
    save(fig, "05_gt2820_06_single_point.png", rect=(0, 0.1, 1, 0.86))


if __name__ == "__main__":
    import sys
    only = sys.argv[1:]
    for f in (fig_summary, fig_system, fig_gt2820, fig_aeronaut_curves, fig_apc_curves):
        if not only or f.__name__ in only:
            f()
    sys.exit(0)
    fig_summary()
    fig_system()
    fig_gt2820()
    fig_aeronaut_curves()
    fig_apc_curves()
