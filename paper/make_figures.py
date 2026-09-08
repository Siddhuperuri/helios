# -*- coding: utf-8 -*-
"""
Figures for the IEEE Access version of the paper.

Every value plotted here is taken from the measured results already reported
in docs/RESEARCH_SYNTHESIS.md (findings F1-F6). Nothing is simulated.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

BLUE = "#0073AE"
DARK = "#1a1a1a"
GREY = "#8c8c8c"
LIGHT = "#cfe3f0"
RED = "#b03030"

plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Times New Roman", "DejaVu Serif"],
    "font.size": 8,
    "axes.edgecolor": "#444444",
    "axes.linewidth": 0.7,
    "xtick.major.width": 0.6,
    "ytick.major.width": 0.6,
    "savefig.dpi": 400,
})


def save(fig, name):
    fig.savefig(name, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("wrote", name)


# ---------------------------------------------------------------- FIGURE 1
fig, ax = plt.subplots(figsize=(6.6, 1.85))
ax.set_xlim(0, 100)
ax.set_ylim(0, 26)
ax.axis("off")
stages = [
    ("Location\n(lat, lon)", 2.0),
    ("ERA5 hourly\nweather", 18.6),
    ("Interval-label\ncorrection", 35.2),
    ("Solar geometry\n+ clear-sky index", 51.8),
    ("Four-model\nensemble", 68.4),
    ("Conformal\nintervals", 85.0),
]
for label, x in stages:
    ax.add_patch(FancyBboxPatch((x, 8.5), 13.2, 9.5,
                                boxstyle="round,pad=0.35,rounding_size=0.8",
                                linewidth=1.0, edgecolor=BLUE, facecolor=LIGHT))
    ax.text(x + 6.6, 13.2, label, ha="center", va="center",
            fontsize=7.4, color=DARK)
for _, x in stages[:-1]:
    ax.add_patch(FancyArrowPatch((x + 13.5, 13.2), (x + 16.3, 13.2),
                                 arrowstyle="-|>", mutation_scale=8,
                                 linewidth=0.9, color=BLUE))
ax.text(50, 2.8,
        "Chronological split + embargo + rolling-origin CV; "
        "night hours excluded at zenith < 87 deg",
        ha="center", va="center", fontsize=7.2, color=GREY, style="italic")
save(fig, "fig1_pipeline.png")

# ---------------------------------------------------------------- FIGURE 2
offsets = [-60, -30, 0, 30]
exceed = [360, 0, 264, 697]
corr = [0.9340, 0.9490, 0.9372, 0.8998]
labels = [str(o) for o in offsets]

fig, ax1 = plt.subplots(figsize=(3.3, 2.35))
cols = [BLUE if o != -30 else "#00507a" for o in offsets]
bars = ax1.bar(labels, exceed, width=0.6, color=cols,
               edgecolor="black", linewidth=0.5, zorder=3)
bars[1].set_hatch("///")
ax1.set_xlabel("Offset applied to solar-position timestamp (min)", fontsize=7.5)
ax1.set_ylabel("Clear-sky exceedances per year", fontsize=7.5, color=DARK)
ax1.set_ylim(0, 790)
ax1.grid(axis="y", linestyle=":", linewidth=0.5, color="#bbbbbb", zorder=0)
for b, v in zip(bars, exceed):
    ax1.text(b.get_x() + b.get_width() / 2, v + 20, str(v),
             ha="center", fontsize=7, color=DARK)
ax2 = ax1.twinx()
ax2.plot(labels, corr, marker="o", markersize=4, color=RED,
         linewidth=1.2, zorder=4)
ax2.set_ylabel("corr(GHI, clear-sky)", fontsize=7.5, color=RED)
ax2.tick_params(axis="y", labelcolor=RED, labelsize=7)
ax2.set_ylim(0.885, 0.962)
ax1.tick_params(labelsize=7)
ax1.annotate("selected", xy=(1, 30), xytext=(1.62, 330), fontsize=7, ha="center",
             color="#00507a",
             arrowprops=dict(arrowstyle="->", color="#00507a", linewidth=0.8))
save(fig, "fig2_interval.png")

# ---------------------------------------------------------------- FIGURE 3
strat = ["Chronological", "Blocked random\n(whole days)", "Random\n(hour level)"]
rmse = [74.68, 68.97, 66.03]
r2 = [0.9160, 0.9376, 0.9427]
tri = [BLUE, "#4a9ac9", "#9ec9e2"]

fig, axes = plt.subplots(1, 2, figsize=(6.6, 2.2))
b1 = axes[0].bar(strat, rmse, width=0.58, color=tri,
                 edgecolor="black", linewidth=0.5, zorder=3)
axes[0].set_ylabel("RMSE (W/m$^2$)", fontsize=7.5)
axes[0].set_ylim(60, 79)
axes[0].grid(axis="y", linestyle=":", linewidth=0.5, color="#bbbbbb", zorder=0)
for b, v in zip(b1, rmse):
    axes[0].text(b.get_x() + b.get_width() / 2, v + 0.4, "%.2f" % v,
                 ha="center", fontsize=7)
axes[0].annotate("", xy=(2, 66.03), xytext=(0, 74.68),
                 arrowprops=dict(arrowstyle="<->", color=RED, linewidth=0.9))
axes[0].text(1.0, 71.9, "-11.6%", ha="center", fontsize=7.5,
             color=RED, fontweight="bold")

b2 = axes[1].bar(strat, r2, width=0.58, color=tri,
                 edgecolor="black", linewidth=0.5, zorder=3)
axes[1].set_ylabel("$R^2$", fontsize=7.5)
axes[1].set_ylim(0.905, 0.951)
axes[1].grid(axis="y", linestyle=":", linewidth=0.5, color="#bbbbbb", zorder=0)
for b, v in zip(b2, r2):
    axes[1].text(b.get_x() + b.get_width() / 2, v + 0.0017, "%.4f" % v,
                 ha="center", fontsize=7)
axes[1].text(1.0, 0.9440, "+0.027", ha="center", fontsize=7.5,
             color=RED, fontweight="bold")
for a in axes:
    a.tick_params(axis="x", labelsize=7)
    a.tick_params(axis="y", labelsize=7)
save(fig, "fig3_split.png")

# ---------------------------------------------------------------- FIGURE 4
labs = ["All hours", "Clear", "Cloudy", "Precip."]
after = [80.2, 80.3, 80.0, 80.9]
fig, ax = plt.subplots(figsize=(3.3, 2.35))
xs = list(range(len(labs)))
ax.axhspan(78, 82, color="#e8f2f8", zorder=0)
ax.axhline(80, color=RED, linestyle="--", linewidth=0.9, zorder=2,
           label="nominal 80%")
ax.bar([xs[0] - 0.19], [66.3], width=0.36, color="#c0c0c0",
       edgecolor="black", linewidth=0.5, zorder=3, label="uncalibrated")
ax.bar([i + 0.19 for i in xs], after, width=0.36, color=BLUE,
       edgecolor="black", linewidth=0.5, zorder=3, label="conformalized")
ax.text(-0.19, 67.4, "66.3", ha="center", fontsize=7)
for i, v in zip(xs, after):
    ax.text(i + 0.19, v + 1.3, "%.1f" % v, ha="center", fontsize=7)
ax.set_xticks(xs)
ax.set_xticklabels(labs, fontsize=7.5)
ax.set_ylabel("Empirical coverage (%)", fontsize=7.5)
ax.set_ylim(60, 90)
ax.tick_params(axis="y", labelsize=7)
ax.legend(fontsize=6.3, loc="lower right", framealpha=0.95)
ax.grid(axis="y", linestyle=":", linewidth=0.5, color="#bbbbbb", zorder=0)
save(fig, "fig4_coverage.png")

# ---------------------------------------------------------------- FIGURE 5
groups = ["Temperature\n& moisture", "Cloud &\nprecipitation", "Solar\ngeometry",
          "Time of\nyear / day", "Pressure", "Wind"]
share = [52.0, 21.0, 17.0, 6.0, 3.0, 1.5]
fig, ax = plt.subplots(figsize=(3.3, 2.35))
ypos = list(range(len(groups)))[::-1]
bars = ax.barh(ypos, share, height=0.62, color=BLUE,
               edgecolor="black", linewidth=0.5, zorder=3)
bars[2].set_color(RED)
ax.set_yticks(ypos)
ax.set_yticklabels(groups, fontsize=7)
ax.set_xlabel("Share of measured effect (%)", fontsize=7.5)
ax.set_xlim(0, 62)
ax.tick_params(axis="x", labelsize=7)
for b, v in zip(bars, share):
    ax.text(v + 1.4, b.get_y() + b.get_height() / 2, "%.1f" % v,
            va="center", fontsize=7)
ax.grid(axis="x", linestyle=":", linewidth=0.5, color="#bbbbbb", zorder=0)
ax.text(27, 3.05, "geometry ranks 3rd when the\ntarget is the clear-sky index",
        fontsize=6.5, color=RED, style="italic")
save(fig, "fig5_importance.png")

# ---------------------------------------------------------------- FIGURE 6
fig, ax = plt.subplots(figsize=(3.3, 2.35))
ax.axhline(0, color="black", linewidth=0.8, zorder=2)
ax.bar(0, 114.3, width=0.55, color="#4a9ac9", edgecolor="black",
       linewidth=0.5, zorder=3)
ax.bar(1, -105.7, width=0.55, color=RED, edgecolor="black",
       linewidth=0.5, zorder=3)
ax.bar(2, 8.6, width=0.55, color=BLUE, edgecolor="black",
       linewidth=0.5, zorder=3)
ax.plot([0.28, 0.72], [114.3, 114.3], linestyle=":", color=GREY, linewidth=0.8)
ax.plot([1.28, 1.72], [8.6, 8.6], linestyle=":", color=GREY, linewidth=0.8)
for xx, v in [(0, 114.3), (1, -105.7), (2, 8.6)]:
    ax.text(xx, v + (7 if v > 0 else -15), "%+.1f" % v, ha="center", fontsize=7.2)
ax.set_xticks([0, 1, 2])
ax.set_xticklabels(["Statistical\n(correlational)", "Physical\n(causal)", "Net"],
                   fontsize=7)
ax.set_ylabel("Energy change (kWh)", fontsize=7.5)
ax.set_ylim(-138, 142)
ax.tick_params(axis="y", labelsize=7)
ax.grid(axis="y", linestyle=":", linewidth=0.5, color="#bbbbbb", zorder=0)
save(fig, "fig6_scenario.png")

print("all figures done")
