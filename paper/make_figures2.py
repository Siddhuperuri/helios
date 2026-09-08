# -*- coding: utf-8 -*-
"""Column-width replacements for Figures 1 and 3 (IEEE Access column = 3.37in)."""
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
    "savefig.dpi": 400,
})

# ------------------------------------------------------------- FIGURE 1
# Boustrophedon layout: row 1 runs left-to-right, row 2 right-to-left, so the
# connector between rows is a single clean vertical arrow that crosses nothing.
fig, ax = plt.subplots(figsize=(3.3, 2.15))
ax.set_xlim(0, 100)
ax.set_ylim(0, 62)
ax.axis("off")

BW, BH = 27.5, 15.5
XS = [3.0, 36.2, 69.4]
Y1, Y2 = 42.0, 17.0

row1 = [("Location\n(lat, lon)", XS[0]),
        ("ERA5 hourly\nweather", XS[1]),
        ("Interval-label\ncorrection", XS[2])]
row2 = [("Conformal\nintervals", XS[0]),
        ("Four-model\nensemble", XS[1]),
        ("Solar geometry\n+ clear-sky index", XS[2])]

for label, x in row1:
    ax.add_patch(FancyBboxPatch((x, Y1), BW, BH,
                                boxstyle="round,pad=0.4,rounding_size=1.2",
                                linewidth=1.0, edgecolor=BLUE, facecolor=LIGHT))
    ax.text(x + BW / 2, Y1 + BH / 2, label, ha="center", va="center",
            fontsize=6.9, color=DARK)
for label, x in row2:
    ax.add_patch(FancyBboxPatch((x, Y2), BW, BH,
                                boxstyle="round,pad=0.4,rounding_size=1.2",
                                linewidth=1.0, edgecolor=BLUE, facecolor=LIGHT))
    ax.text(x + BW / 2, Y2 + BH / 2, label, ha="center", va="center",
            fontsize=6.9, color=DARK)

# row 1: left to right
for x in XS[:2]:
    ax.add_patch(FancyArrowPatch((x + BW + 0.6, Y1 + BH / 2),
                                 (x + BW + 4.6, Y1 + BH / 2),
                                 arrowstyle="-|>", mutation_scale=8,
                                 linewidth=0.9, color=BLUE))
# row 2: right to left
for x in XS[1:]:
    ax.add_patch(FancyArrowPatch((x - 0.6, Y2 + BH / 2),
                                 (x - 4.6, Y2 + BH / 2),
                                 arrowstyle="-|>", mutation_scale=8,
                                 linewidth=0.9, color=BLUE))
# single vertical connector down the right-hand side
ax.add_patch(FancyArrowPatch((XS[2] + BW / 2, Y1 - 0.6),
                             (XS[2] + BW / 2, Y2 + BH + 0.6),
                             arrowstyle="-|>", mutation_scale=8,
                             linewidth=0.9, color=BLUE))

ax.text(50, 5.5,
        "Chronological split + embargo + rolling-origin CV;\n"
        "night hours excluded at zenith < 87 deg",
        ha="center", va="center", fontsize=6.8, color=GREY, style="italic")
fig.savefig("fig1_pipeline.png", bbox_inches="tight", facecolor="white")
plt.close(fig)
print("wrote fig1_pipeline.png")

# ------------------------------------------------------------- FIGURE 3
strat = ["Chronological", "Blocked random\n(whole days)", "Random\n(hour level)"]
rmse = [74.68, 68.97, 66.03]
r2 = [0.9160, 0.9376, 0.9427]
tri = [BLUE, "#4a9ac9", "#9ec9e2"]

fig, axes = plt.subplots(2, 1, figsize=(3.3, 3.5))

b1 = axes[0].bar(strat, rmse, width=0.55, color=tri,
                 edgecolor="black", linewidth=0.5, zorder=3)
axes[0].set_ylabel("RMSE (W/m$^2$)", fontsize=7.5)
axes[0].set_ylim(60, 80)
axes[0].grid(axis="y", linestyle=":", linewidth=0.5, color="#bbbbbb", zorder=0)
for b, v in zip(b1, rmse):
    axes[0].text(b.get_x() + b.get_width() / 2, v + 0.5, "%.2f" % v,
                 ha="center", fontsize=7)
axes[0].annotate("", xy=(2, 66.03), xytext=(0, 74.68),
                 arrowprops=dict(arrowstyle="<->", color=RED, linewidth=0.9))
axes[0].text(1.0, 72.3, "-11.6%", ha="center", fontsize=7.5,
             color=RED, fontweight="bold")
axes[0].set_xticklabels([])

b2 = axes[1].bar(strat, r2, width=0.55, color=tri,
                 edgecolor="black", linewidth=0.5, zorder=3)
axes[1].set_ylabel("$R^2$", fontsize=7.5)
axes[1].set_ylim(0.905, 0.952)
axes[1].grid(axis="y", linestyle=":", linewidth=0.5, color="#bbbbbb", zorder=0)
for b, v in zip(b2, r2):
    axes[1].text(b.get_x() + b.get_width() / 2, v + 0.0018, "%.4f" % v,
                 ha="center", fontsize=7)
axes[1].text(1.0, 0.9445, "+0.027", ha="center", fontsize=7.5,
             color=RED, fontweight="bold")

for a in axes:
    a.tick_params(axis="x", labelsize=6.9)
    a.tick_params(axis="y", labelsize=7)
fig.tight_layout(h_pad=0.8)
fig.savefig("fig3_split.png", bbox_inches="tight", facecolor="white")
plt.close(fig)
print("wrote fig3_split.png")
