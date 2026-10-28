"""Comparison plots for validate.py."""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

INK, INK2, GRID, SURFACE, BAND = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb", "#ecebe7"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]     # fixed categorical order


def _style(ax):
    ax.set_facecolor(SURFACE)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(INK2)
    ax.tick_params(colors=INK2, labelsize=8)


def curves_figure(curves, configs, labels, props, out):
    colors = dict(zip(configs, SERIES))
    fig, axes = plt.subplots(3, len(props), figsize=(3.2 * len(props), 8.2), sharex="col")
    fig.patch.set_facecolor(SURFACE)
    for col, name in enumerate(props):
        rpm = min(curves[(name, configs[0])]["runs"])     # lowest-rpm run covers the widest J range
        for row, (idx, ylab) in enumerate(((0, "$C_T$"), (1, "$C_P$"), (None, "Efficiency η"))):
            ax = axes[row, col]
            _style(ax)
            for cfg in configs:
                c = curves[(name, cfg)]["runs"][rpm]
                Jf, mod = c["Jf"], c["model"]
                if idx is None:
                    y = np.where((mod[:, 0] > 0.002) & (mod[:, 1] > 0), Jf * mod[:, 0] / mod[:, 1], np.nan)
                else:
                    y = mod[:, idx]
                ax.plot(Jf, y, color=colors[cfg], linewidth=2, label=labels[cfg])
            d = curves[(name, configs[0])]["runs"][rpm]["meas"]
            y = np.where(d[:, 1] > 0.002, d[:, 3], np.nan) if idx is None else d[:, idx + 1]
            ax.plot(d[:, 0], y, "o", color=INK, markersize=4.5, markeredgecolor=SURFACE,
                    markeredgewidth=0.8, label="UIUC wind tunnel", zorder=5)
            if idx is None:
                ax.set_ylim(0, 0.85)
            else:
                ax.axhline(0, color=INK2, linewidth=0.8)
            if col == 0:
                ax.set_ylabel(ylab, color=INK, fontsize=10)
            if row == 0:
                ax.set_title(f"APC {name}E  ·  {rpm} rpm", color=INK, fontsize=10)
            if row == 2:
                ax.set_xlabel("Advance ratio J", color=INK2, fontsize=9)
    handles, labs = axes[0, 0].get_legend_handles_labels()
    order = [labs.index("UIUC wind tunnel")] + [i for i, l in enumerate(labs) if l != "UIUC wind tunnel"]
    fig.legend([handles[i] for i in order], [labs[i] for i in order], loc="lower center", ncol=4,
               frameon=False, fontsize=9, labelcolor=INK)
    fig.suptitle("XtraProp vs. measured data: thrust, power and efficiency coefficients",
                 color=INK, fontsize=12, x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0.04, 1, 0.97))
    fig.savefig(os.path.join(out, "comparison_curves.png"), dpi=150, facecolor=SURFACE)
    plt.close(fig)


def error_figure(summary, configs, labels, props, out):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharey=True)
    fig.patch.set_facecolor(SURFACE)
    width = 0.8 / len(configs)
    x = np.arange(len(props))
    for ax, key, title in ((axes[0], "static_CT_err_pct", "Static thrust error"),
                           (axes[1], "static_CP_err_pct", "Static power error")):
        _style(ax)
        ax.axhspan(-5, 5, color=BAND, zorder=0)
        ax.axhline(0, color=INK2, linewidth=0.8)
        for i, cfg in enumerate(configs):
            vals = [next(r[key] for r in summary if r["prop"] == p and r["config"] == cfg) for p in props]
            ax.bar(x + (i - (len(configs) - 1) / 2) * width, vals, width - 0.03, color=SERIES[i],
                   label=labels[cfg], zorder=3)
        ax.set_xticks(x, [f"{p}E" for p in props])
        ax.set_title(title, color=INK, fontsize=11, loc="left")
        ax.tick_params(axis="x", colors=INK, labelsize=9)
    axes[0].set_ylabel("Model vs. measured (%)", color=INK, fontsize=9)
    axes[1].text(len(props) - 0.55, -4.6, "±5% band", color=INK2, fontsize=8, ha="right")
    handles, labs = axes[0].get_legend_handles_labels()
    fig.legend(handles, labs, loc="lower center", ncol=len(configs), frameon=False, fontsize=9, labelcolor=INK)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(os.path.join(out, "static_errors.png"), dpi=150, facecolor=SURFACE)
    plt.close(fig)


def make_all(summary, curves, configs, labels, props, out):
    curves_figure(curves, configs, labels, props, out)
    error_figure(summary, configs, labels, props, out)
    print(f"Plots written to {out}")
