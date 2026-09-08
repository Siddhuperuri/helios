# -*- coding: utf-8 -*-
"""
Typesets the paper as a two-column IEEE-conference-style PDF using ReportLab.

This is a faithful visual approximation of the IEEEtran conference template
(US Letter, two columns of 3.5in with a 0.25in gutter, Times 10pt body).
For an *official* submission, compile paper/helios_paper.tex on Overleaf with
pdfLaTeX so the output is genuine IEEEtran.
"""
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer,
    Table, TableStyle, NextPageTemplate, KeepTogether,
)

OUT = r"C:\Projects_AI\college_project\paper\helios_paper.pdf"
F = r"C:\Windows\Fonts"

pdfmetrics.registerFont(TTFont("Times", F + r"\times.ttf"))
pdfmetrics.registerFont(TTFont("Times-Bd", F + r"\timesbd.ttf"))
pdfmetrics.registerFont(TTFont("Times-It", F + r"\timesi.ttf"))
pdfmetrics.registerFont(TTFont("Times-BdIt", F + r"\timesbi.ttf"))
pdfmetrics.registerFontFamily("Times", normal="Times", bold="Times-Bd",
                              italic="Times-It", boldItalic="Times-BdIt")

PW, PH = LETTER
LM = RM = 0.625 * inch
TM = 0.75 * inch
BM = 1.0 * inch
COLW = 3.5 * inch
GUT = 0.25 * inch
TITLE_H = 2.78 * inch

# ---------------------------------------------------------------- styles
S = {}
S["title"] = ParagraphStyle("title", fontName="Times-Bd", fontSize=21, leading=25,
                            alignment=TA_CENTER, spaceAfter=12)
S["auth"] = ParagraphStyle("auth", fontName="Times", fontSize=11, leading=13.5,
                           alignment=TA_CENTER)
S["aff"] = ParagraphStyle("aff", fontName="Times-It", fontSize=10, leading=12.5,
                          alignment=TA_CENTER)
S["abs"] = ParagraphStyle("abs", fontName="Times-Bd", fontSize=9, leading=11,
                          alignment=TA_JUSTIFY, spaceAfter=6)
S["idx"] = ParagraphStyle("idx", fontName="Times-Bd", fontSize=9, leading=11,
                          alignment=TA_JUSTIFY, spaceAfter=10)
S["sec"] = ParagraphStyle("sec", fontName="Times", fontSize=10, leading=12,
                          alignment=TA_CENTER, spaceBefore=11, spaceAfter=5)
S["sub"] = ParagraphStyle("sub", fontName="Times-It", fontSize=10, leading=12,
                          alignment=TA_LEFT, spaceBefore=7, spaceAfter=3)
S["body"] = ParagraphStyle("body", fontName="Times", fontSize=10, leading=11.8,
                           alignment=TA_JUSTIFY, firstLineIndent=10, spaceAfter=1)
S["body0"] = ParagraphStyle("body0", parent=S["body"], firstLineIndent=0)
S["item"] = ParagraphStyle("item", fontName="Times", fontSize=10, leading=11.8,
                           alignment=TA_JUSTIFY, leftIndent=14, firstLineIndent=-10,
                           spaceAfter=4)
S["tcap"] = ParagraphStyle("tcap", fontName="Times", fontSize=8, leading=9.6,
                           alignment=TA_CENTER, spaceBefore=8, spaceAfter=4)
S["tc"] = ParagraphStyle("tc", fontName="Times", fontSize=8, leading=9.4,
                         alignment=TA_CENTER)
S["tcb"] = ParagraphStyle("tcb", fontName="Times-Bd", fontSize=8, leading=9.4,
                          alignment=TA_CENTER)
S["tl"] = ParagraphStyle("tl", fontName="Times", fontSize=8, leading=9.4,
                         alignment=TA_LEFT)
S["tlb"] = ParagraphStyle("tlb", fontName="Times-Bd", fontSize=8, leading=9.4,
                          alignment=TA_LEFT)
S["ref"] = ParagraphStyle("ref", fontName="Times", fontSize=8, leading=9.5,
                          alignment=TA_JUSTIFY, leftIndent=12, firstLineIndent=-12,
                          spaceAfter=2)
S["ack"] = ParagraphStyle("ack", fontName="Times", fontSize=9, leading=11,
                          alignment=TA_JUSTIFY, spaceAfter=3)
S["secns"] = ParagraphStyle("secns", parent=S["sec"])


def P(t, st="body"):
    return Paragraph(t, S[st])


def sec(n, t):
    return Paragraph(f"{n}.&nbsp;&nbsp;{t.upper()}", S["sec"])


def secx(t):
    return Paragraph(t.upper(), S["secns"])


def sub(letter, t):
    return Paragraph(f"<i>{letter}. {t}</i>", S["sub"])


def rule(w, lw=0.9):
    tb = Table([[""]], colWidths=[w], rowHeights=[0.4])
    tb.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), lw, colors.black),
                            ("TOPPADDING", (0, 0), (-1, -1), 0),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return tb


def mktable(caption_no, caption, header, rows, widths, bold_rows=()):
    """IEEE-style: caption above, horizontal rules only."""
    cap = Paragraph(f"TABLE {caption_no}<br/><font name='Times-It'>{caption}</font>",
                    S["tcap"])
    data = [[Paragraph(h, S["tcb"]) for h in header]]
    for i, r in enumerate(rows):
        st = "tcb" if i in bold_rows else "tc"
        stl = "tlb" if i in bold_rows else "tl"
        data.append([Paragraph(str(c), S[stl] if j == 0 else S[st])
                     for j, c in enumerate(r)])
    t = Table(data, colWidths=widths, hAlign="CENTER")
    t.setStyle(TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEABOVE", (0, 0), (-1, 0), 1.0, colors.black),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.black),
        ("LINEBELOW", (0, -1), (-1, -1), 1.0, colors.black),
    ]))
    return KeepTogether([cap, t, Spacer(1, 8)])


# ---------------------------------------------------------------- content
story = []

story.append(Paragraph(
    "Quantifying Three Evaluation Pitfalls in "
    "Machine-Learning Solar Forecasting: Split Optimism, "
    "Interval-Label Phase Error, and Prediction-Interval Miscalibration",
    S["title"]))
story.append(Paragraph(
    "T. Harshini Sowmya, M. Lavanya Durga, P. J. S. Siddhartha, "
    "M. Ajay Prakash, P. Maruthi Sreeram, and K. Surya Prakash", S["auth"]))
story.append(Spacer(1, 4))
story.append(Paragraph(
    "Department of Computer Science and Engineering<br/>"
    "&lt;Institution Name&gt;, &lt;City&gt;, India<br/>"
    "Team CSE-D_13", S["aff"]))

story.append(NextPageTemplate("later"))

story.append(P(
    "<i>Abstract</i>\u2014Machine-learning solar forecasting is routinely reported "
    "with coefficients of determination above 0.9, yet several widely used "
    "evaluation practices inflate those figures in ways that are invisible in the "
    "published result. We reconcile six recent solar-forecasting studies into a "
    "single reproducible platform and use it to quantify three such effects on "
    "identical data, models and random seeds. First, random train/test splitting "
    "of an autocorrelated hourly series understates RMSE by 11.6% (74.68 to 66.03 "
    "W/m<super>2</super>) and overstates R<super>2</super> by 0.027 relative to a "
    "chronological split\u2014the comparison that one of the reconciled studies "
    "explicitly names as future work. Second, we determine empirically that hourly "
    "reanalysis irradiance is labelled at the <i>end</i> of its averaging interval; "
    "evaluating solar position at the raw label rather than the interval midpoint "
    "introduces a systematic phase error yielding 264 spurious clear-sky "
    "exceedances per year, and correcting it raises our data-quality score from "
    "97.7% to 99.9%. Third, uncalibrated quantile gradient boosting attains only "
    "66.3% empirical coverage for a nominal 80% prediction interval; conformalized "
    "quantile regression restores coverage to 80.2% and to within two points in "
    "every weather regime. We additionally show that permutation feature importance "
    "is contingent on target choice, which reconciles two apparently contradictory "
    "published importance rankings, and that a scenario response can conceal two "
    "large opposing pathways that nearly cancel. None of these findings requires "
    "metered plant output: each is a controlled comparison in which only the "
    "disputed methodological choice varies. We argue that reporting them should be "
    "routine, and release the platform and its reproducibility manifest to make "
    "doing so inexpensive.", "abs"))

story.append(P(
    "<i>Index Terms</i>\u2014solar irradiance forecasting, photovoltaic systems, "
    "ensemble learning, time-series cross-validation, conformal prediction, "
    "reproducibility, ERA5 reanalysis.", "idx"))

# ---- I. Introduction
story.append(sec("I", "Introduction"))
story.append(P(
    "Solar generation is variable on every timescale that matters to an operator, "
    "and the machine-learning literature addressing that variability has grown "
    "quickly. Recent studies report strong goodness-of-fit: R<super>2</super> near "
    "or above 0.9 is common, and ensemble methods\u2014random forests, boosted "
    "trees, and stacked combinations\u2014are consistently among the best "
    "performers [2], [4], [5].", "body0"))
story.append(P(
    "The difficulty is that a headline R<super>2</super> is a function not only of "
    "the model but of a set of evaluation choices that are frequently made in "
    "passing and reported in a single clause. Whether night hours are retained, "
    "whether the split respects chronology, whether the target was statistically "
    "truncated, and whether a stated prediction interval actually covers what it "
    "claims are all decisions that move the reported number substantially. Because "
    "they are rarely varied within a single study, their magnitude is difficult for "
    "a reader to judge."))
story.append(P(
    "This paper takes six recent solar-forecasting studies [1]\u2013[6], implements "
    "their common methodological core in one platform, and then uses that platform "
    "to hold everything constant except one disputed choice at a time. The result "
    "is a set of effect sizes rather than a set of recommendations."))

story.append(sub("A", "Contributions"))
story.append(P(
    "1)&nbsp;&nbsp;<i>Split optimism, measured.</i> With identical model, seed and "
    "data, random hour-level splitting understates RMSE by 11.6% and overstates "
    "R<super>2</super> by +0.027 against a chronological split. Blocked random "
    "splitting by whole days recovers about half the gap (Section V-B).", "item"))
story.append(P(
    "2)&nbsp;&nbsp;<i>The interval-label convention, determined empirically.</i> "
    "Reanalysis irradiance is an interval average while solar position is "
    "instantaneous. We sweep candidate offsets over a full year and show the "
    "representative instant lies 30 minutes <i>before</i> the label, eliminating "
    "clear-sky exceedances entirely (Section V-A). We are not aware of this "
    "convention being established by measurement elsewhere in the applied solar-ML "
    "literature, and a defect it exposed in our own code is reported alongside it.",
    "item"))
story.append(P(
    "3)&nbsp;&nbsp;<i>Interval miscalibration, measured and corrected.</i> A nominal "
    "80% interval from plain quantile gradient boosting covered 66.3% of "
    "observations. Conformalized quantile regression [14] restores 80.2% coverage "
    "overall and holds within two points across clear, cloudy and precipitation "
    "regimes (Section V-C).", "item"))
story.append(P(
    "4)&nbsp;&nbsp;<i>Target-dependent feature importance.</i> Grouped permutation "
    "importance ranks solar geometry third when the target is the clear-sky index "
    "but dominant when the target is raw power, which reconciles [5] with [2] "
    "rather than adjudicating between them (Section V-D).", "item"))
story.append(P(
    "5)&nbsp;&nbsp;<i>A reproducible platform.</i> All comparisons run from one "
    "codebase against a keyless public data source, with a reproducibility "
    "manifest, so a reader can repeat them on their own coordinates.", "item"))
story.append(P(
    "A deliberate non-contribution: we make <i>no</i> claim of state-of-the-art "
    "forecast accuracy. Section VII states why our setup cannot support one, and "
    "why the contributions above do not require it.", "body0"))

# ---- II. Related Work
story.append(sec("II", "Related Work"))
story.append(sub("A", "Targets and models"))
story.append(P(
    "The six reconciled studies do not share a prediction target. Four predict "
    "irradiance\u2014global horizontal irradiance (GHI) in W/m<super>2</super> [2], "
    "[3], [4], or global solar radiation [4]\u2014while the remainder predict PV "
    "power directly [1], [5], [6]. The two are related by a deterministic physical "
    "chain once array geometry and rating are declared [1].", "body0"))
story.append(P(
    "We adopt GHI as the primary scientific target, because it is the quantity "
    "actually measured and its meaning does not depend on an installation, and "
    "treat PV energy as a derived engineering output obtained through an explicit, "
    "user-visible system model. Reporting \u201ckWh\u201d without a declared array "
    "size, tilt and period is not a well-posed target, and we regard the separation "
    "as a correction rather than a preference."))
story.append(P(
    "On models, the corpus converges on tree ensembles. Random forests [9] appear "
    "in [2], [4], [5]; boosted trees in [2]\u2013[5]; and stacking [12] is the best "
    "overall performer in [4]. Deep sequence models are explored in [6]. We retain "
    "four estimators\u2014random forest, histogram gradient boosting [11], extremely "
    "randomised trees [10], and ridge regression [13] as a deliberate linear "
    "floor\u2014together with a stacked combination of the four using a ridge "
    "meta-learner. Second representatives of a family already present were "
    "withdrawn: a longer comparison table is not a stronger result."))

story.append(sub("B", "Evaluation practice"))
story.append(P(
    "Our concern is with the evaluation layer, where the corpus is less uniform.",
    "body0"))
story.append(P(
    "<i>Splitting.</i> [2] uses a random split and describes it as preventing "
    "leakage. For an autocorrelated series this places observations minutes apart "
    "on both sides of the boundary. [5] is explicit that its \u201cvalidation was "
    "performed using random sampling\u201d and names time-based splitting as future "
    "work. Section V-B supplies that measurement."))
story.append(P(
    "<i>Target truncation.</i> [4] applies interquartile-range outlier bounds of "
    "165\u2013331 W/m<super>2</super> to solar radiation and removes 10.16% of "
    "observations. Clear-sky midday GHI at the study's latitude exceeds 900 "
    "W/m<super>2</super>, so the procedure removes physically valid high-irradiance "
    "data and compresses the range against which an RMSE of 47.30 "
    "W/m<super>2</super> is subsequently reported. We apply physical-range "
    "validation only."))
story.append(P(
    "<i>Metric definition.</i> The quantity defined as \u201crelative MAE\u201d in "
    "[2] is mean(|O\u2212F|/F), which is MAPE rather than MAE normalised by the mean "
    "of observations\u2014the convention that same work uses for relative RMSE. We "
    "compute and label MAE, rMAE and MAPE separately."))
story.append(P(
    "<i>Night hours.</i> Any model trivially predicts zero at night, and retaining "
    "night hours inflates R<super>2</super> because between-group day/night variance "
    "dominates the total sum of squares. [2], [3], [4] all exclude night. We adopt "
    "the solar-zenith criterion of [3] (\u03b8<sub>z</sub> &lt; 87\u00b0), the only "
    "physically defined rule among them; fixed clock windows are latitude-dependent "
    "and fail at high latitude."))
story.append(P(
    "These are observations about method, not allegations of error. Each is a choice "
    "that a reader cannot presently price, which is what Section V sets out to "
    "change."))

# ---- III. Data and System
story.append(sec("III", "Data and System"))
story.append(sub("A", "Data source"))
story.append(P(
    "All meteorological inputs are hourly ERA5 and ERA5-Land reanalysis [7], "
    "retrieved through the Open-Meteo Historical Weather API [8] without an API "
    "key. Retrieved variables are GHI (shortwave radiation), direct normal and "
    "diffuse irradiance, air temperature, relative humidity, dew point, surface "
    "pressure, wind speed and direction, cloud cover and precipitation.", "body0"))
story.append(P(
    "This is reanalysis, not pyranometer data: a modelled gridded product "
    "representing a cell of order 9\u201325 km rather than a sensor at a specific "
    "address. This bounds comparability\u2014our figures are not directly comparable "
    "to the ground-station measurements of [2] or the on-site station of [4]\u2014and "
    "we state it wherever results are reported. Data are CC-BY 4.0; ERA5 is "
    "\u00a9 ECMWF/Copernicus."))
story.append(P(
    "Experiments in Section V use two to three years of hourly data at Hyderabad, "
    "India (17.385\u00b0N, 78.487\u00b0E), typically ~26,000 hours. Incomplete hours "
    "are dropped and reported, never imputed; we do not manufacture observations on "
    "which we then report metrics."))

story.append(sub("B", "Physical chain"))
story.append(P(
    "PV energy is obtained from irradiance through published models applied in "
    "sequence: Erbs decomposition [16] to separate diffuse and direct components; "
    "HDKR transposition to the plane of array [17]; the Faiman cell-temperature "
    "model [18]; the PVWatts v5 DC model [19] with a nameplate temperature "
    "coefficient; a multiplicative loss stack; and inverter efficiency with AC "
    "clipping. Clear-sky reference irradiance uses the Haurwitz model [20].",
    "body0"))

story.append(sub("C", "Feature construction and the clear-sky index"))
story.append(P(
    "Rather than predicting GHI directly, models predict the clear-sky index "
    "k<sub>t</sub> = GHI / GHI<sub>cs</sub>, following [1]. Dividing out "
    "deterministic geometry leaves the atmospheric component\u2014which is what a "
    "learned model can actually contribute\u2014and has a direct consequence for "
    "feature attribution that Section V-D makes explicit.", "body0"))
story.append(P(
    "Standardisation is fitted <i>inside</i> each cross-validation fold on training "
    "data only. Fitting a scaler on the full dataset before splitting leaks test-set "
    "statistics, and does so in a way that no subsequent metric will reveal."))

# ---- IV. Methodology
story.append(sec("IV", "Methodology"))
story.append(sub("A", "Validation protocol"))
story.append(P(
    "Unless a comparison is explicitly about the split, all reported metrics use a "
    "chronological split with an embargo between train and test segments, and "
    "rolling-origin cross-validation. Night hours are excluded by the "
    "\u03b8<sub>z</sub> &lt; 87\u00b0 criterion in training and in every reported "
    "metric.", "body0"))

story.append(sub("B", "Metrics"))
story.append(P(
    "We report MAE, RMSE, rMAE and rRMSE (each normalised by the mean of "
    "observations), MAPE with a zero-denominator guard, R<super>2</super>, "
    "Nash\u2013Sutcliffe efficiency, and mean bias error. Probabilistic forecasts "
    "additionally report pinball loss, empirical coverage (PICP), normalised "
    "interval width (PINAW), and CRPS computed empirically from quantiles [15]. "
    "Skill scores are computed against persistence, clear-sky persistence, and "
    "hour-of-year climatology.", "body0"))
story.append(P(
    "Train-set metrics are never reported alone, only beside validation metrics, and "
    "a large gap is flagged. This is a direct response to [2], where "
    "distance-weighted k-NN attains a training relative RMSE of 0.41% against 5.77% "
    "on test\u2014train metrics for such a model describe interpolation, not "
    "generalisation."))

# ---- V. Results
story.append(sec("V", "Results"))
story.append(P(
    "Each subsection isolates one methodological choice. Model, seed, feature set "
    "and data are identical within each comparison; only the disputed element "
    "varies.", "body0"))

story.append(sub("A", "The interval-label convention"))
story.append(P(
    "Irradiance in an hourly archive is a mean over an interval, whereas solar "
    "position is instantaneous. If position is evaluated at the interval <i>label</i> "
    "rather than at the interval's representative instant, a systematic phase error "
    "follows. The convention is not documented in a form we could rely on, so we "
    "measured it, sweeping candidate offsets over a full year (Table I).", "body0"))

story.append(mktable(
    "I",
    "Interval-offset sweep, Hyderabad, one year. The offset is applied to the "
    "timestamp at which solar position is evaluated.",
    ["Offset (min)", "Clear-sky exceed.", "Apparent night irrad.", "corr(GHI, cs)"],
    [["\u221260", "360", "289", "0.9340"],
     ["\u221230", "0", "216", "0.9490"],
     ["0", "264", "265", "0.9372"],
     ["+30", "697", "428", "0.8998"]],
    [0.68 * inch, 0.80 * inch, 0.88 * inch, 0.74 * inch],
    bold_rows=(1,)))

story.append(P(
    "The \u221230 minute offset is the unique candidate producing zero physically "
    "impossible clear-sky exceedances, and it simultaneously maximises correlation "
    "with the clear-sky reference. We conclude that hourly radiation is the mean "
    "over the <i>preceding</i> hour and the representative instant is 30 minutes "
    "before the label. Applying the correction raised the platform's data-quality "
    "score from 97.7% to 99.9%.", "body0"))
story.append(P(
    "Two points deserve emphasis. First, the naive choice\u2014offset zero\u2014is "
    "not merely suboptimal but produces 264 physically impossible observations per "
    "year, which any downstream physical-range check will then either flag or "
    "silently absorb. Second, the sweep exposed a genuine defect in our own "
    "implementation: the PV chain evaluated solar position at the raw label while "
    "the feature pipeline used the midpoint, a 30-minute inconsistency that "
    "displaced the day/night boundary by a full hour at the terminator. It was "
    "caught by a test asserting zero PV output at night. We report it because the "
    "class of error is easy to introduce and invisible in aggregate metrics."))

story.append(sub("B", "Split optimism"))
story.append(P("Table II varies only the splitting strategy.", "body0"))

story.append(mktable(
    "II",
    "Effect of splitting strategy. Identical model, seed and dataset; "
    "two years, Hyderabad.",
    ["Strategy", "RMSE (W/m<super>2</super>)", "R<super>2</super>"],
    [["Chronological", "74.68", "0.9160"],
     ["Blocked random (days)", "68.97", "0.9376"],
     ["Random (hour level)", "66.03", "0.9427"]],
    [1.55 * inch, 0.95 * inch, 0.75 * inch]))

story.append(P(
    "Hour-level random splitting understates RMSE by 11.6% and overstates "
    "R<super>2</super> by +0.027. Blocking by whole days recovers roughly half the "
    "gap, which is consistent with the mechanism: the leak is driven by "
    "near-neighbour hours straddling the boundary, and blocking removes the "
    "within-day cases while leaving day-to-day persistence intact.", "body0"))
story.append(P(
    "An 11.6% RMSE difference is comparable to the margin by which competing models "
    "are separated in several published comparisons. Where a study reports a random "
    "split, that margin is therefore not safely interpretable as a model difference. "
    "This substantiates quantitatively the concern that [5] raises about its own "
    "protocol."))

story.append(sub("C", "Prediction-interval calibration"))
story.append(P(
    "An interval that does not cover what it claims is worse than no interval, "
    "because it will be relied upon. Quantile gradient boosting trained directly for "
    "the 10th and 90th percentiles produced a nominal 80% interval with 66.3% "
    "empirical coverage. Applying conformalized quantile regression [14] restores "
    "calibration (Table III).", "body0"))

story.append(mktable(
    "III",
    "Empirical coverage of a nominal 80% prediction interval, before and after "
    "conformal calibration.",
    ["Condition", "Coverage (%)"],
    [["Uncalibrated quantile GBM, all hours", "66.3"],
     ["Conformalized, all hours", "80.2"],
     ["&nbsp;&nbsp;&nbsp;clear regime", "80.3"],
     ["&nbsp;&nbsp;&nbsp;cloudy regime", "80.0"],
     ["&nbsp;&nbsp;&nbsp;precipitation regime", "80.9"]],
    [2.15 * inch, 1.05 * inch]))

story.append(P(
    "Coverage holds within two points inside every weather regime, using the regime "
    "thresholds of [3]. Conformal calibration is not drawn from the reconciled "
    "corpus and we label it an enhancement rather than an implementation of prior "
    "work.", "body0"))
story.append(P(
    "We also implemented and tested a seasonally stratified calibration split. It "
    "did not robustly improve coverage: results were non-monotone in its parameters "
    "(0.700, 0.725, 0.706, 0.790 as the embargo widened; 0.767 against 0.834 for six "
    "versus eight blocks). Non-monotone response to a parameter that should act "
    "smoothly is instability, not signal, and selecting the best-scoring "
    "configuration would have been tuning on the test set. The simpler contiguous "
    "split was retained. We report the negative result because the "
    "alternative\u2014reporting only the configuration that scored best\u2014is "
    "precisely the practice that produces irreproducible intervals."))

story.append(sub("D", "Feature importance depends on the target"))
story.append(P(
    "Grouped permutation importance, predicting the clear-sky index at Hyderabad, is "
    "given in Table IV.", "body0"))

story.append(mktable(
    "IV",
    "Grouped permutation importance when predicting the clear-sky index. "
    "Shares of measured effect.",
    ["Feature group", "Share (%)"],
    [["Temperature and moisture", "52.0"],
     ["Cloud and precipitation", "21.0"],
     ["Solar geometry", "17.0"],
     ["Time of year / day", "6.0"],
     ["Pressure", "3.0"],
     ["Wind", "1.5"]],
    [1.95 * inch, 1.05 * inch]))

story.append(P(
    "Solar geometry ranks third, whereas [5] finds geometry\u2014angle of incidence "
    "in particular\u2014dominant. The results are consistent rather than "
    "contradictory. [5] predicts raw PV power, in which geometry is the largest "
    "single driver; we divide geometry out before fitting, so what remains for the "
    "model to explain is the atmospheric component. In that residual space humidity "
    "and cloud dominate, which agrees with [2] finding temperature and humidity the "
    "leading meteorological predictors.", "body0"))
story.append(P(
    "The methodological point generalises: a feature-importance ranking is a "
    "statement about a target, not about solar energy. Two studies reporting "
    "different rankings may both be correct, and comparing their rankings without "
    "first reconciling their targets is not meaningful."))

story.append(sub("E", "Baselines coincide at day-ahead horizons"))
story.append(P(
    "Naive persistence and clear-sky (\u201csmart\u201d) persistence score 143.4 and "
    "143.3 W/m<super>2</super> respectively at a 24-hour horizon. This is expected "
    "rather than anomalous: solar declination changes by at most ~0.4\u00b0 per day, "
    "so k<sub>t</sub>(t\u221224h) \u00b7 GHI<sub>cs</sub>(t) \u2248 "
    "GHI(t\u221224h). The two diverge sharply at intra-day horizons. It is also why "
    "baselines must be formed in physical units: in clear-sky-index space they are "
    "algebraically the same function and the comparison would be vacuous. A reported "
    "day-ahead improvement over \u201csmart persistence\u201d should therefore be "
    "checked against naive persistence, which at that horizon is the same baseline.",
    "body0"))

story.append(sub("F", "Scenario responses can conceal opposing pathways"))
story.append(P(
    "A perturbation scenario of +6\u00b0C with halved wind speed returned a net "
    "energy change of +0.29%\u2014counter-intuitive, since hotter modules are less "
    "efficient. Decomposition (Table V) shows two large opposing pathways.", "body0"))

story.append(mktable(
    "V",
    "Decomposition of a +6\u00b0C, halved-wind scenario.",
    ["Pathway", "Effect (kWh)"],
    [["Statistical (warm hours tend to be sunny)", "+114.3"],
     ["Physical (hotter modules less efficient)", "\u2212105.7"],
     ["Net", "+8.6"]],
    [2.15 * inch, 1.05 * inch],
    bold_rows=(2,)))

story.append(P(
    "The learned correlation and the causal physical response are of comparable "
    "magnitude and opposite sign. Reporting the net figure alone would conceal this, "
    "and would invite the reader to attribute a near-zero response to insensitivity "
    "rather than to cancellation. We surface both pathways separately. Doubling wind "
    "speed instead shows the causal pathway dominating (+43.2 kWh thermal against "
    "\u22127.0 kWh statistical), the physically expected result.", "body0"))
story.append(P(
    "This is a general hazard for any scenario analysis conducted with a model "
    "trained on observational data: the model has learned correlations that a "
    "counterfactual intervention does not preserve."))

# ---- VI. Discussion
story.append(sec("VI", "Discussion"))
story.append(P(
    "The effects reported here are not exotic. Each arises from a choice that is "
    "ordinary, defensible in isolation, and rarely varied within a single study. "
    "Their magnitudes, however, are on the same scale as the differences by which "
    "published models are separated: an 11.6% RMSE shift from splitting alone, a "
    "14-point coverage shortfall from omitting calibration, and a feature ranking "
    "that reorders entirely with the choice of target.", "body0"))
story.append(P(
    "We therefore suggest three reporting practices, each cheap once implemented. "
    "First, state the splitting strategy and, where a random split is used, report "
    "the chronological figure alongside it; the comparison costs one additional fit. "
    "Second, report empirical coverage whenever a prediction interval is shown, "
    "since a nominal level is an intention and not a measurement. Third, state the "
    "prediction target precisely enough that a feature-importance ranking can be "
    "interpreted, which for PV energy means declaring array size, tilt and period."))
story.append(P(
    "None of this requires agreement with our modelling choices. The comparisons are "
    "internal: each holds the model fixed and varies only the practice under "
    "examination."))

# ---- VII. Limitations
story.append(sec("VII", "Limitations and Threats to Validity"))
story.append(P(
    "We state these plainly because they bound what the paper claims.", "body0"))
story.append(P(
    "<i>Modelled, not measured.</i> No metered generation from an installed system "
    "was available to us. Every PV energy figure is a physical chain applied to "
    "reanalysis weather and has <i>not</i> been validated against real production. "
    "We consequently make no claim about absolute forecast accuracy against physical "
    "plant, and readers should not extract one. The findings in Section V are "
    "controlled internal comparisons, in which the absence of plant ground truth "
    "affects both arms equally and therefore does not threaten the contrast\u2014but "
    "this is an argument for the specific claims made, not a general licence."))
story.append(P(
    "<i>Reanalysis, not a pyranometer.</i> ERA5 represents a grid cell, not a point. "
    "Local haze, dust and coastal cloud may differ materially from the cell average, "
    "and our figures are not directly comparable to studies using ground stations."))
story.append(P(
    "<i>Single-site experiments.</i> The measurements in Section V were conducted at "
    "one location. The mechanisms are general\u2014autocorrelation, interval "
    "labelling, quantile miscalibration\u2014but the effect <i>sizes</i> should be "
    "expected to vary with climate, and particularly with the frequency of rapid "
    "cloud transitions. Multi-site replication is the most immediate extension."))
story.append(P(
    "<i>Interval-label finding is source-specific.</i> The \u221230 minute result "
    "characterises this archive's convention. The measurement procedure transfers to "
    "other sources; the offset should not be assumed to."))
story.append(P(
    "<i>Scope.</i> Deep sequence models [6] and full copula-based dynamic feature "
    "selection [3] are not implemented, and are labelled as future work rather than "
    "approximated."))

# ---- VIII. Conclusion
story.append(sec("VIII", "Conclusion"))
story.append(P(
    "We reconciled six solar-forecasting studies into one platform and used it to "
    "price three evaluation choices that the literature generally leaves unpriced. "
    "Random splitting of autocorrelated hourly data understates RMSE by 11.6% and "
    "overstates R<super>2</super> by 0.027. Hourly reanalysis irradiance is labelled "
    "at the end of its averaging interval, and ignoring this produces 264 physically "
    "impossible observations per year at a single site. A nominal 80% prediction "
    "interval from uncalibrated quantile regression covered 66.3% of observations, "
    "which conformal calibration restored to 80.2% across every weather regime. We "
    "further showed that permutation importance is a statement about a target rather "
    "than about solar energy, reconciling two published rankings, and that a "
    "scenario response can hide two large opposing pathways.", "body0"))
story.append(P(
    "Future work is field validation against metered generation, which is the one "
    "thing that would let accuracy claims be made at all; multi-site replication to "
    "establish how the effect sizes vary with climate; and extension to the deep "
    "sequence models the corpus identifies but this work does not implement."))

story.append(secx("Reproducibility"))
story.append(P(
    "The platform, the reproducibility manifest, and the interval calibration script "
    "used for Table I accompany this submission. All meteorological inputs come from "
    "a keyless public API, so every experiment can be repeated at arbitrary "
    "coordinates without credentials or a data-use agreement.", "ack"))

story.append(secx("Acknowledgment"))
story.append(P(
    "The authors thank the Department of Computer Science and Engineering for "
    "supporting this work. Weather and solar-resource data are provided by Open-Meteo "
    "under CC-BY 4.0; ERA5 is \u00a9 ECMWF/Copernicus.", "ack"))

# ---- References
story.append(secx("References"))
REFS = [
    "R. Hobbs and S. Joshi, \u201cUsing open-source forecasts for solar plant "
    "maintenance outage scheduling can reduce lost energy,\u201d <i>IEEE J. "
    "Photovoltaics</i>, 2026, accepted for publication.",
    "T. Mabodi and J. Hammujuddy, \u201cSolar irradiance forecasting for informed "
    "solar systems design and financing decisions,\u201d <i>SAIEE Africa Research "
    "Journal</i>, vol. 115, no. 3, 2024.",
    "Y. Lyu and S. Eftekharnejad, \u201cProbabilistic solar generation forecasting "
    "for rapidly changing weather conditions,\u201d <i>IEEE Access</i>, vol. 12, 2024.",
    "J. Rosales Huamani <i>et al.</i>, \u201cEfficient ML models for solar radiation "
    "prediction using ensemble techniques: A case study in low-rainfall arid "
    "climates,\u201d <i>IEEE Access</i>, vol. 13, 2025.",
    "K. Vijay Babu <i>et al.</i>, \u201cSolar energy forecasting using machine "
    "learning techniques for enhanced grid stability,\u201d <i>IEEE Access</i>, "
    "vol. 13, 2025.",
    "M. Hayajneh <i>et al.</i>, \u201cIntelligent solar forecasts: Modern ML models "
    "and TinyML role for improved solar energy yield predictions,\u201d <i>IEEE "
    "Access</i>, vol. 12, 2024.",
    "H. Hersbach <i>et al.</i>, \u201cThe ERA5 global reanalysis,\u201d <i>Q. J. R. "
    "Meteorol. Soc.</i>, vol. 146, no. 730, pp. 1999\u20132049, 2020.",
    "P. Zippenfenig, \u201cOpen-Meteo.com weather API,\u201d 2023. [Online]. "
    "Available: https://open-meteo.com",
    "L. Breiman, \u201cRandom forests,\u201d <i>Machine Learning</i>, vol. 45, no. 1, "
    "pp. 5\u201332, 2001.",
    "P. Geurts, D. Ernst, and L. Wehenkel, \u201cExtremely randomized trees,\u201d "
    "<i>Machine Learning</i>, vol. 63, no. 1, pp. 3\u201342, 2006.",
    "G. Ke <i>et al.</i>, \u201cLightGBM: A highly efficient gradient boosting "
    "decision tree,\u201d in <i>Advances in Neural Information Processing "
    "Systems</i>, vol. 30, 2017.",
    "D. H. Wolpert, \u201cStacked generalization,\u201d <i>Neural Networks</i>, "
    "vol. 5, no. 2, pp. 241\u2013259, 1992.",
    "A. E. Hoerl and R. W. Kennard, \u201cRidge regression: Biased estimation for "
    "nonorthogonal problems,\u201d <i>Technometrics</i>, vol. 12, no. 1, "
    "pp. 55\u201367, 1970.",
    "Y. Romano, E. Patterson, and E. Cand\u00e8s, \u201cConformalized quantile "
    "regression,\u201d in <i>Advances in Neural Information Processing Systems</i>, "
    "vol. 32, 2019.",
    "T. Gneiting and A. E. Raftery, \u201cStrictly proper scoring rules, prediction, "
    "and estimation,\u201d <i>J. Amer. Statist. Assoc.</i>, vol. 102, no. 477, "
    "pp. 359\u2013378, 2007.",
    "D. G. Erbs, S. A. Klein, and J. A. Duffie, \u201cEstimation of the diffuse "
    "radiation fraction for hourly, daily and monthly-average global "
    "radiation,\u201d <i>Solar Energy</i>, vol. 28, no. 4, pp. 293\u2013302, 1982.",
    "J. A. Duffie and W. A. Beckman, <i>Solar Engineering of Thermal Processes</i>, "
    "4th ed. Hoboken, NJ, USA: Wiley, 2013.",
    "D. Faiman, \u201cAssessing the outdoor operating temperature of photovoltaic "
    "modules,\u201d <i>Progress in Photovoltaics</i>, vol. 16, no. 4, "
    "pp. 307\u2013315, 2008.",
    "A. P. Dobos, \u201cPVWatts version 5 manual,\u201d National Renewable Energy "
    "Laboratory, Golden, CO, USA, Tech. Rep. NREL/TP-6A20-62641, 2014.",
    "B. Haurwitz, \u201cInsolation in relation to cloudiness and cloud "
    "density,\u201d <i>J. Meteorology</i>, vol. 2, no. 1, pp. 1\u20138, 1945.",
    "F. Pedregosa <i>et al.</i>, \u201cScikit-learn: Machine learning in "
    "Python,\u201d <i>J. Machine Learning Research</i>, vol. 12, "
    "pp. 2825\u20132830, 2011.",
]
for i, r in enumerate(REFS, 1):
    story.append(Paragraph(f"[{i}]&nbsp;&nbsp;{r}", S["ref"]))


# ---------------------------------------------------------------- document
doc = BaseDocTemplate(OUT, pagesize=LETTER,
                      leftMargin=LM, rightMargin=RM,
                      topMargin=TM, bottomMargin=BM,
                      title="Quantifying Three Evaluation Pitfalls in "
                            "Machine-Learning Solar Forecasting",
                      author="Team CSE-D_13")

full_w = PW - LM - RM
body_h = PH - TM - BM

f_title = Frame(LM, PH - TM - TITLE_H, full_w, TITLE_H,
                leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
f_p1a = Frame(LM, BM, COLW, body_h - TITLE_H,
              leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
f_p1b = Frame(LM + COLW + GUT, BM, COLW, body_h - TITLE_H,
              leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
f_la = Frame(LM, BM, COLW, body_h,
             leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
f_lb = Frame(LM + COLW + GUT, BM, COLW, body_h,
             leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)

doc.addPageTemplates([
    PageTemplate(id="first", frames=[f_title, f_p1a, f_p1b]),
    PageTemplate(id="later", frames=[f_la, f_lb]),
])

doc.build(story)
print("Saved to", OUT)
