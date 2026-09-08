# -*- coding: utf-8 -*-
"""
Content + assembly for the IEEE Access version.

    python make_access.py                -> author manuscript (what you submit)
    python make_access.py --published    -> mock of the typeset article

The manuscript mode omits everything IEEE adds at production: the Access
wordmark, the Received/accepted/DOI block, the RESEARCH ARTICLE badge, the
volume/page footers and the CC-BY notice. Authors never supply those.
"""
import sys

from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer,
    NextPageTemplate, FrameBreak, KeepTogether,
)

from build_access_pdf import (
    OUT, PW, PH, LM, RM, GUT, COLW, BODY_TOP, BODY_BOT, BODY_H,
    BLUE, BLACK, RUNNING_HEAD, S, P, SEC, SUB, SSUB,
    AccessBadge, DottedMark, access_logo, tbl, figure, bio,
)

CW = COLW
FW = PW - LM - RM          # full text width

PUBLISHED = "--published" in sys.argv
OUTFILE = OUT if PUBLISHED else OUT.replace("_ieee_access.pdf",
                                            "_ieee_access_manuscript.pdf")

# ===================================================================== front
front = []
if PUBLISHED:
    front.append(Spacer(1, 26))
    front.append(P("Received &lt;DD MONTH YYYY&gt;, accepted &lt;DD MONTH YYYY&gt;, "
                   "date of publication &lt;DD MONTH YYYY&gt;, date of current "
                   "version &lt;DD MONTH YYYY&gt;.", "dates"))
    front.append(P("Digital Object Identifier &lt;10.1109/ACCESS.YYYY.NNNNNNN&gt;",
                   "doi"))
    front.append(Spacer(1, 12))
    front.append(AccessBadge(FW))
    front.append(Spacer(1, 12))
else:
    front.append(Spacer(1, 8))
front.append(P("Quantifying Three Evaluation Pitfalls in Machine-Learning "
               "Solar Forecasting: Split Optimism, Interval-Label Phase Error, "
               "and Prediction-Interval Miscalibration", "title"))
front.append(P("T. HARSHINI SOWMYA<super>1</super>, M. LAVANYA DURGA<super>1</super>, "
               "P. J. S. SIDDHARTHA<super>1</super>,<br/>"
               "M. AJAY PRAKASH<super>1</super>, P. MARUTHI SREERAM<super>1</super>, "
               "AND K. SURYA PRAKASH<super>1</super>", "authors"))
front.append(P("<super>1</super>Department of Computer Science and Engineering, "
               "&lt;Institution Name&gt;, &lt;City&gt;, &lt;PIN&gt;, India", "affil"))
front.append(P("Corresponding author: &lt;Author Name&gt; "
               "(&lt;corresponding.author@institution.edu&gt;)", "corr"))
if not PUBLISHED:
    front.append(P("This work was supported by &lt;FUNDING SOURCE AND GRANT "
                   "NUMBER, or state that the work received no external "
                   "funding&gt;.", "corr"))

front.append(DottedMark())
front.append(P(
    '<font name="Ar-B" color="#0073AE" size="9">ABSTRACT</font> '
    "Machine-learning solar forecasting is routinely reported with coefficients "
    "of determination above 0.9, yet several widely used evaluation practices "
    "inflate those figures in ways that are invisible in the published result. "
    "We reconcile six recent solar-forecasting studies into a single reproducible "
    "platform and use it to quantify three such effects on identical data, models "
    "and random seeds. First, random train/test splitting of an autocorrelated "
    "hourly series understates RMSE by 11.6% (74.68 to 66.03 W/m<super>2</super>) "
    "and overstates R<super>2</super> by 0.027 relative to a chronological "
    "split&#8212;the comparison that one of the reconciled studies explicitly "
    "names as future work. Second, we determine empirically that hourly "
    "reanalysis irradiance is labelled at the <i>end</i> of its averaging "
    "interval; evaluating solar position at the raw label rather than the "
    "interval midpoint introduces a systematic phase error yielding 264 spurious "
    "clear-sky exceedances per year, and correcting it raises our data-quality "
    "score from 97.7% to 99.9%. Third, uncalibrated quantile gradient boosting "
    "attains only 66.3% empirical coverage for a nominal 80% prediction interval; "
    "conformalized quantile regression restores coverage to 80.2% and to within "
    "two points in every weather regime. We additionally show that permutation "
    "feature importance is contingent on target choice, which reconciles two "
    "apparently contradictory published importance rankings, and that a scenario "
    "response can conceal two large opposing pathways that nearly cancel. None of "
    "these findings requires metered plant output: each is a controlled comparison "
    "in which only the disputed methodological choice varies. We argue that "
    "reporting them should be routine, and release the platform and its "
    "reproducibility manifest to make doing so inexpensive.", "abs"))
front.append(DottedMark())
front.append(P(
    '<font name="Ar-B" color="#0073AE" size="9">INDEX TERMS</font> '
    "Conformal prediction, ensemble learning, ERA5 reanalysis, photovoltaic "
    "systems, reproducibility, solar irradiance forecasting, time-series "
    "cross-validation.", "idx"))
front.append(Spacer(1, 6))

# ====================================================================== body
body = []

body.append(SEC("I", "Introduction"))
body.append(P(
    "Solar generation is variable on every timescale that matters to an operator, "
    "and the machine-learning literature addressing that variability has grown "
    "quickly. Recent studies report strong goodness-of-fit: R<super>2</super> near "
    "or above 0.9 is common, and ensemble methods&#8212;random forests, boosted "
    "trees, and stacked combinations&#8212;are consistently among the best "
    "performers [2], [4], [5].", "body0"))
body.append(P(
    "The difficulty is that a headline R<super>2</super> is a function not only of "
    "the model but of a set of evaluation choices that are frequently made in "
    "passing and reported in a single clause. Whether night hours are retained, "
    "whether the split respects chronology, whether the target was statistically "
    "truncated, and whether a stated prediction interval actually covers what it "
    "claims are all decisions that move the reported number substantially. Because "
    "they are rarely varied within a single study, their magnitude is difficult "
    "for a reader to judge."))
body.append(P(
    "This paper takes six recent solar-forecasting studies [1]&#8211;[6], "
    "implements their common methodological core in one platform, and then uses "
    "that platform to hold everything constant except one disputed choice at a "
    "time. The result is a set of effect sizes rather than a set of "
    "recommendations."))

body.append(SUB("A", "Contributions"))
for n, t in [
    (1, "<i>Split optimism, measured.</i> With identical model, seed and data, "
        "random hour-level splitting understates RMSE by 11.6% and overstates "
        "R<super>2</super> by +0.027 against a chronological split. Blocked "
        "random splitting by whole days recovers about half the gap "
        "(Section IV-B)."),
    (2, "<i>The interval-label convention, determined empirically.</i> "
        "Reanalysis irradiance is an interval average while solar position is "
        "instantaneous. We sweep candidate offsets over a full year and show the "
        "representative instant lies 30 minutes <i>before</i> the label, "
        "eliminating clear-sky exceedances entirely (Section IV-A)."),
    (3, "<i>Interval miscalibration, measured and corrected.</i> A nominal 80% "
        "interval from plain quantile gradient boosting covered 66.3% of "
        "observations. Conformalized quantile regression [14] restores 80.2% "
        "coverage overall and holds within two points across clear, cloudy and "
        "precipitation regimes (Section IV-C)."),
    (4, "<i>Target-dependent feature importance.</i> Grouped permutation "
        "importance ranks solar geometry third when the target is the clear-sky "
        "index but dominant when the target is raw power, which reconciles [5] "
        "with [2] rather than adjudicating between them (Section IV-D)."),
    (5, "<i>A reproducible platform.</i> All comparisons run from one codebase "
        "against a keyless public data source, with a reproducibility manifest, "
        "so a reader can repeat them on their own coordinates."),
]:
    body.append(P("%d) %s" % (n, t), "num"))
body.append(P(
    "A deliberate non-contribution: we make <i>no</i> claim of state-of-the-art "
    "forecast accuracy. Section V-C states why our setup cannot support one, and "
    "why the contributions above do not require it.", "body0"))

body.append(SEC("II", "Review of Literature"))
body.append(SUB("A", "Prediction targets and model families"))
body.append(P(
    "The six reconciled studies do not share a prediction target. Four predict "
    "irradiance&#8212;global horizontal irradiance (GHI) in W/m<super>2</super> "
    "[2], [3], [4], or global solar radiation [4]&#8212;while the remainder "
    "predict PV power directly [1], [5], [6]. The two are related by a "
    "deterministic physical chain once array geometry and rating are declared [1].",
    "body0"))
body.append(P(
    "We adopt GHI as the primary scientific target, because it is the quantity "
    "actually measured and its meaning does not depend on an installation, and "
    "treat PV energy as a derived engineering output obtained through an explicit, "
    "user-visible system model. Reporting &#8220;kWh&#8221; without a declared "
    "array size, tilt and period is not a well-posed target, and we regard the "
    "separation as a correction rather than a preference."))
body.append(P(
    "On models, the corpus converges on tree ensembles. Random forests [9] appear "
    "in [2], [4], [5]; boosted trees in [2]&#8211;[5]; and stacking [12] is the "
    "best overall performer in [4]. Deep sequence models are explored in [6]. We "
    "retain four estimators&#8212;random forest, histogram gradient boosting [11], "
    "extremely randomised trees [10], and ridge regression [13] as a deliberate "
    "linear floor&#8212;together with a stacked combination of the four using a "
    "ridge meta-learner. Second representatives of a family already present were "
    "withdrawn: a longer comparison table is not a stronger result."))

body.append(SUB("B", "Evaluation practice in the corpus"))
body.append(P("Our concern is with the evaluation layer, where the corpus is "
              "less uniform.", "body0"))
body.append(P(
    "<i>Splitting.</i> [2] uses a random split and describes it as preventing "
    "leakage. For an autocorrelated series this places observations minutes apart "
    "on both sides of the boundary. [5] is explicit that its &#8220;validation was "
    "performed using random sampling&#8221; and names time-based splitting as "
    "future work. Section IV-B supplies that measurement."))
body.append(P(
    "<i>Target truncation.</i> [4] applies interquartile-range outlier bounds of "
    "165&#8211;331 W/m<super>2</super> to solar radiation and removes 10.16% of "
    "observations. Clear-sky midday GHI at the study's latitude exceeds 900 "
    "W/m<super>2</super>, so the procedure removes physically valid "
    "high-irradiance data and compresses the range against which an RMSE of 47.30 "
    "W/m<super>2</super> is subsequently reported. We apply physical-range "
    "validation only."))
body.append(P(
    "<i>Metric definition.</i> The quantity defined as &#8220;relative MAE&#8221; "
    "in [2] is mean(|O&#8722;F|/F), which is MAPE rather than MAE normalised by "
    "the mean of observations&#8212;the convention that same work uses for "
    "relative RMSE. We compute and label MAE, rMAE and MAPE separately."))
body.append(P(
    "<i>Night hours.</i> Any model trivially predicts zero at night, and retaining "
    "night hours inflates R<super>2</super> because between-group day/night "
    "variance dominates the total sum of squares. [2], [3], [4] all exclude night. "
    "We adopt the solar-zenith criterion of [3] (&#952;<sub>z</sub> &lt; 87&#176;), "
    "the only physically defined rule among them; fixed clock windows are "
    "latitude-dependent and fail at high latitude."))
body.append(P(
    "These are observations about method, not allegations of error. Each is a "
    "choice that a reader cannot presently price, which is what Section IV sets "
    "out to change."))

body.append(SEC("III", "Materials and Methods"))
body.append(figure("1", "Stages of the proposed evaluation platform. Each stage "
                        "is a pure function of its inputs, which is what makes "
                        "the controlled comparisons of Section IV possible.",
                   "fig1_pipeline.png", CW))

body.append(SUB("A", "Data source"))
body.append(P(
    "All meteorological inputs are hourly ERA5 and ERA5-Land reanalysis [7], "
    "retrieved through the Open-Meteo Historical Weather API [8] without an API "
    "key. Retrieved variables are GHI (shortwave radiation), direct normal and "
    "diffuse irradiance, air temperature, relative humidity, dew point, surface "
    "pressure, wind speed and direction, cloud cover and precipitation.", "body0"))
body.append(P(
    "This is reanalysis, not pyranometer data: a modelled gridded product "
    "representing a cell of order 9&#8211;25 km rather than a sensor at a specific "
    "address. This bounds comparability&#8212;our figures are not directly "
    "comparable to the ground-station measurements of [2] or the on-site station "
    "of [4]&#8212;and we state it wherever results are reported. Data are CC-BY "
    "4.0; ERA5 is &#169; ECMWF/Copernicus."))
body.append(P(
    "Experiments in Section IV use two to three years of hourly data at Hyderabad, "
    "India (17.385&#176;N, 78.487&#176;E), typically ~26,000 hours. Incomplete "
    "hours are dropped and reported, never imputed; we do not manufacture "
    "observations on which we then report metrics."))

body.append(SUB("B", "Physical conversion chain"))
body.append(P(
    "PV energy is obtained from irradiance through published models applied in "
    "sequence: Erbs decomposition [16] to separate diffuse and direct components; "
    "HDKR transposition to the plane of array [17]; the Faiman cell-temperature "
    "model [18]; the PVWatts v5 DC model [19] with a nameplate temperature "
    "coefficient; a multiplicative loss stack; and inverter efficiency with AC "
    "clipping. Clear-sky reference irradiance uses the Haurwitz model [20].",
    "body0"))

body.append(SUB("C", "Feature construction and the clear-sky index"))
body.append(P(
    "Rather than predicting GHI directly, models predict the clear-sky index "
    "k<sub>t</sub> = GHI / GHI<sub>cs</sub>, following [1]. Dividing out "
    "deterministic geometry leaves the atmospheric component&#8212;which is what a "
    "learned model can actually contribute&#8212;and has a direct consequence for "
    "feature attribution that Section IV-D makes explicit.", "body0"))
body.append(P(
    "Standardisation is fitted <i>inside</i> each cross-validation fold on "
    "training data only. Fitting a scaler on the full dataset before splitting "
    "leaks test-set statistics, and does so in a way that no subsequent metric "
    "will reveal."))

body.append(SUB("D", "Validation protocol"))
body.append(P(
    "Unless a comparison is explicitly about the split, all reported metrics use a "
    "chronological split with an embargo between train and test segments, and "
    "rolling-origin cross-validation. Night hours are excluded by the "
    "&#952;<sub>z</sub> &lt; 87&#176; criterion in training and in every reported "
    "metric.", "body0"))

body.append(SUB("E", "Evaluation metrics"))
body.append(P(
    "We report MAE, RMSE, rMAE and rRMSE (each normalised by the mean of "
    "observations), MAPE with a zero-denominator guard, R<super>2</super>, "
    "Nash&#8211;Sutcliffe efficiency, and mean bias error. Probabilistic forecasts "
    "additionally report pinball loss, empirical coverage (PICP), normalised "
    "interval width (PINAW), and CRPS computed empirically from quantiles [15]. "
    "Skill scores are computed against persistence, clear-sky persistence, and "
    "hour-of-year climatology.", "body0"))
body.append(P(
    "Train-set metrics are never reported alone, only beside validation metrics, "
    "and a large gap is flagged. This is a direct response to [2], where "
    "distance-weighted k-NN attains a training relative RMSE of 0.41% against "
    "5.77% on test&#8212;train metrics for such a model describe interpolation, "
    "not generalisation."))

body.append(SEC("IV", "Experimental Results"))
body.append(P(
    "Each subsection isolates one methodological choice. Model, seed, feature set "
    "and data are identical within each comparison; only the disputed element "
    "varies.", "body0"))

body.append(SUB("A", "The interval-label convention"))
body.append(P(
    "Irradiance in an hourly archive is a mean over an interval, whereas solar "
    "position is instantaneous. If position is evaluated at the interval "
    "<i>label</i> rather than at the interval's representative instant, a "
    "systematic phase error follows. The convention is not documented in a form we "
    "could rely on, so we measured it, sweeping candidate offsets over a full year "
    "(Table 1, Fig. 2).", "body0"))
body.append(tbl("1", "Interval-offset sweep, Hyderabad, one year. The offset is "
                     "applied to the timestamp at which solar position is "
                     "evaluated.",
                ["Offset (min)", "Clear-sky exceedances",
                 "Apparent night irradiance", "corr(GHI, clear-sky)"],
                [["&#8722;60", "360", "289", "0.9340"],
                 ["&#8722;30", "0", "216", "0.9490"],
                 ["0", "264", "265", "0.9372"],
                 ["+30", "697", "428", "0.8998"]],
                [CW * 0.20, CW * 0.28, CW * 0.28, CW * 0.24],
                left_first=False, bold_rows=(1,)))
body.append(figure("2", "Clear-sky exceedances (bars, left axis) and correlation "
                        "with the clear-sky reference (line, right axis) against "
                        "the offset applied to the solar-position timestamp.",
                   "fig2_interval.png", CW))
body.append(P(
    "The &#8722;30 minute offset is the unique candidate producing zero physically "
    "impossible clear-sky exceedances, and it simultaneously maximises correlation "
    "with the clear-sky reference. We conclude that hourly radiation is the mean "
    "over the <i>preceding</i> hour and the representative instant is 30 minutes "
    "before the label. Applying the correction raised the platform's data-quality "
    "score from 97.7% to 99.9%.", "body0"))
body.append(P(
    "Two points deserve emphasis. First, the naive choice&#8212;offset "
    "zero&#8212;is not merely suboptimal but produces 264 physically impossible "
    "observations per year, which any downstream physical-range check will then "
    "either flag or silently absorb. Second, the sweep exposed a genuine defect in "
    "our own implementation: the PV chain evaluated solar position at the raw label "
    "while the feature pipeline used the midpoint, a 30-minute inconsistency that "
    "displaced the day/night boundary by a full hour at the terminator. It was "
    "caught by a test asserting zero PV output at night. We report it because the "
    "class of error is easy to introduce and invisible in aggregate metrics."))

body.append(SUB("B", "Split optimism"))
body.append(P("Table 2 and Fig. 3 vary only the splitting strategy.", "body0"))
body.append(tbl("2", "Effect of splitting strategy. Identical model, seed and "
                     "dataset; two years, Hyderabad.",
                ["Strategy", "RMSE (W/m<super>2</super>)", "R<super>2</super>"],
                [["Chronological", "74.68", "0.9160"],
                 ["Blocked random (whole days)", "68.97", "0.9376"],
                 ["Random (hour level)", "66.03", "0.9427"]],
                [CW * 0.50, CW * 0.28, CW * 0.22]))
body.append(figure("3", "RMSE (top) and R<super>2</super> (bottom) under three "
                        "splitting strategies. Only the split differs.",
                   "fig3_split.png", CW))
body.append(P(
    "Hour-level random splitting understates RMSE by 11.6% and overstates "
    "R<super>2</super> by +0.027. Blocking by whole days recovers roughly half the "
    "gap, which is consistent with the mechanism: the leak is driven by "
    "near-neighbour hours straddling the boundary, and blocking removes the "
    "within-day cases while leaving day-to-day persistence intact.", "body0"))
body.append(P(
    "An 11.6% RMSE difference is comparable to the margin by which competing "
    "models are separated in several published comparisons. Where a study reports "
    "a random split, that margin is therefore not safely interpretable as a model "
    "difference. This substantiates quantitatively the concern that [5] raises "
    "about its own protocol."))

body.append(SUB("C", "Prediction-interval calibration"))
body.append(P(
    "An interval that does not cover what it claims is worse than no interval, "
    "because it will be relied upon. Quantile gradient boosting trained directly "
    "for the 10th and 90th percentiles produced a nominal 80% interval with 66.3% "
    "empirical coverage. Applying conformalized quantile regression [14] restores "
    "calibration (Table 3, Fig. 4).", "body0"))
body.append(tbl("3", "Empirical coverage of a nominal 80% prediction interval, "
                     "before and after conformal calibration.",
                ["Condition", "Coverage (%)"],
                [["Uncalibrated quantile GBM, all hours", "66.3"],
                 ["Conformalized, all hours", "80.2"],
                 ["&nbsp;&nbsp;&nbsp;clear regime", "80.3"],
                 ["&nbsp;&nbsp;&nbsp;cloudy regime", "80.0"],
                 ["&nbsp;&nbsp;&nbsp;precipitation regime", "80.9"]],
                [CW * 0.68, CW * 0.32]))
body.append(figure("4", "Empirical coverage against the nominal 80% level. The "
                        "shaded band marks &#177;2 percentage points.",
                   "fig4_coverage.png", CW))
body.append(P(
    "Coverage holds within two points inside every weather regime, using the "
    "regime thresholds of [3]. Conformal calibration is not drawn from the "
    "reconciled corpus and we label it an enhancement rather than an "
    "implementation of prior work.", "body0"))
body.append(P(
    "We also implemented and tested a seasonally stratified calibration split. It "
    "did not robustly improve coverage: results were non-monotone in its "
    "parameters (0.700, 0.725, 0.706, 0.790 as the embargo widened; 0.767 against "
    "0.834 for six versus eight blocks). Non-monotone response to a parameter that "
    "should act smoothly is instability, not signal, and selecting the "
    "best-scoring configuration would have been tuning on the test set. The "
    "simpler contiguous split was retained. We report the negative result because "
    "the alternative&#8212;reporting only the configuration that scored "
    "best&#8212;is precisely the practice that produces irreproducible intervals."))

body.append(SUB("D", "Feature importance depends on the target"))
body.append(P(
    "Grouped permutation importance, predicting the clear-sky index at Hyderabad, "
    "is given in Table 4 and Fig. 5.", "body0"))
body.append(tbl("4", "Grouped permutation importance when predicting the "
                     "clear-sky index. Shares of measured effect.",
                ["Feature group", "Share (%)"],
                [["Temperature and moisture", "52.0"],
                 ["Cloud and precipitation", "21.0"],
                 ["Solar geometry", "17.0"],
                 ["Time of year / day", "6.0"],
                 ["Pressure", "3.0"],
                 ["Wind", "1.5"]],
                [CW * 0.68, CW * 0.32]))
body.append(figure("5", "Grouped permutation importance for the clear-sky index "
                        "target. Solar geometry (highlighted) ranks third.",
                   "fig5_importance.png", CW))
body.append(P(
    "Solar geometry ranks third, whereas [5] finds geometry&#8212;angle of "
    "incidence in particular&#8212;dominant. The results are consistent rather "
    "than contradictory. [5] predicts raw PV power, in which geometry is the "
    "largest single driver; we divide geometry out before fitting, so what remains "
    "for the model to explain is the atmospheric component. In that residual space "
    "humidity and cloud dominate, which agrees with [2] finding temperature and "
    "humidity the leading meteorological predictors.", "body0"))
body.append(P(
    "The methodological point generalises: a feature-importance ranking is a "
    "statement about a target, not about solar energy. Two studies reporting "
    "different rankings may both be correct, and comparing their rankings without "
    "first reconciling their targets is not meaningful."))

body.append(SUB("E", "Baseline coincidence at day-ahead horizons"))
body.append(P(
    "Naive persistence and clear-sky (&#8220;smart&#8221;) persistence score 143.4 "
    "and 143.3 W/m<super>2</super> respectively at a 24-hour horizon. This is "
    "expected rather than anomalous: solar declination changes by at most "
    "~0.4&#176; per day, so k<sub>t</sub>(t&#8722;24h) &#183; "
    "GHI<sub>cs</sub>(t) &#8776; GHI(t&#8722;24h). The two diverge sharply at "
    "intra-day horizons. It is also why baselines must be formed in physical "
    "units: in clear-sky-index space they are algebraically the same function and "
    "the comparison would be vacuous. A reported day-ahead improvement over "
    "&#8220;smart persistence&#8221; should therefore be checked against naive "
    "persistence, which at that horizon is the same baseline.", "body0"))

body.append(SUB("F", "Scenario pathway decomposition"))
body.append(P(
    "A perturbation scenario of +6&#176;C with halved wind speed returned a net "
    "energy change of +0.29%&#8212;counter-intuitive, since hotter modules are "
    "less efficient. Decomposition (Table 5, Fig. 6) shows two large opposing "
    "pathways.", "body0"))
body.append(tbl("5", "Decomposition of a +6&#176;C, halved-wind scenario.",
                ["Pathway", "Effect (kWh)"],
                [["Statistical (warm hours tend to be sunny)", "+114.3"],
                 ["Physical (hotter modules less efficient)", "&#8722;105.7"],
                 ["Net", "+8.6"]],
                [CW * 0.68, CW * 0.32], bold_rows=(2,)))
body.append(figure("6", "The learned correlational pathway and the causal "
                        "physical pathway are of comparable magnitude and "
                        "opposite sign; the net response conceals both.",
                   "fig6_scenario.png", CW))
body.append(P(
    "Reporting the net figure alone would conceal this, and would invite the "
    "reader to attribute a near-zero response to insensitivity rather than to "
    "cancellation. We surface both pathways separately. Doubling wind speed "
    "instead shows the causal pathway dominating (+43.2 kWh thermal against "
    "&#8722;7.0 kWh statistical), the physically expected result.", "body0"))
body.append(P(
    "This is a general hazard for any scenario analysis conducted with a model "
    "trained on observational data: the model has learned correlations that a "
    "counterfactual intervention does not preserve."))

body.append(SEC("V", "Discussion of Results"))
body.append(SUB("A", "Comparison with related work"))
body.append(P(
    "Table 6 places this work beside the reconciled corpus on the four evaluation "
    "dimensions examined here. It is a comparison of <i>practice</i>, not of "
    "accuracy: the studies use different sites, targets and instruments, so their "
    "error figures are not commensurable and we do not tabulate them as though "
    "they were.", "body0"))
body.append(tbl("6", "Evaluation practice across the reconciled corpus. "
                     "&#8220;n/d&#8221; marks a property we could not determine "
                     "from the text available to us; it is not a claim that the "
                     "study omitted it.",
                ["Study", "Target", "Split", "Night excl.", "Interval calib."],
                [["Hobbs &amp; Joshi [1]", "PV power", "n/d", "n/d", "n/d"],
                 ["Mabodi &amp; H. [2]", "GHI", "random", "yes", "none"],
                 ["Lyu &amp; Eft. [3]", "GHI, PV", "n/d", "zenith", "quantile"],
                 ["Rosales H. [4]", "GSR", "random", "clock", "none"],
                 ["Vijay Babu [5]", "PV power", "random", "n/d", "none"],
                 ["Hayajneh [6]", "Farm power", "n/d", "n/d", "none"],
                 ["This work", "GHI (k<sub>t</sub>)", "chronological",
                  "zenith", "conformal"]],
                [CW * 0.26, CW * 0.19, CW * 0.21, CW * 0.16, CW * 0.18],
                bold_rows=(6,)))

body.append(SUB("B", "Alignment with sustainable development goals"))
body.append(P(
    "Accurate, honestly bounded solar forecasts support SDG 7 (affordable and "
    "clean energy) by improving the information available to those sizing and "
    "financing installations, and SDG 13 (climate action) by reducing the reserve "
    "margin that uncertainty in generation forces onto a grid. We note, however, "
    "that a forecast presented with a miscalibrated interval works against both "
    "goals: an 80% interval that covers 66% of outcomes will under-provision "
    "reserve exactly when variability is highest. The calibration result of "
    "Section IV-C is therefore not a technical detail but a precondition for the "
    "claimed benefit.", "body0"))

body.append(SUB("C", "Limitations and threats to validity"))
body.append(P("We state these plainly because they bound what the paper claims.",
              "body0"))
body.append(P(
    "<i>Modelled, not measured.</i> No metered generation from an installed system "
    "was available to us. Every PV energy figure is a physical chain applied to "
    "reanalysis weather and has <i>not</i> been validated against real production. "
    "We consequently make no claim about absolute forecast accuracy against "
    "physical plant, and readers should not extract one. The findings in "
    "Section IV are controlled internal comparisons, in which the absence of plant "
    "ground truth affects both arms equally and therefore does not threaten the "
    "contrast&#8212;but this is an argument for the specific claims made, not a "
    "general licence."))
body.append(P(
    "<i>Reanalysis, not a pyranometer.</i> ERA5 represents a grid cell, not a "
    "point. Local haze, dust and coastal cloud may differ materially from the cell "
    "average, and our figures are not directly comparable to studies using ground "
    "stations."))
body.append(P(
    "<i>Single-site experiments.</i> The measurements in Section IV were conducted "
    "at one location. The mechanisms are general&#8212;autocorrelation, interval "
    "labelling, quantile miscalibration&#8212;but the effect <i>sizes</i> should "
    "be expected to vary with climate, and particularly with the frequency of "
    "rapid cloud transitions. Multi-site replication is the most immediate "
    "extension."))
body.append(P(
    "<i>Interval-label finding is source-specific.</i> The &#8722;30 minute result "
    "characterises this archive's convention. The measurement procedure transfers "
    "to other sources; the offset should not be assumed to."))
body.append(P(
    "<i>Scope.</i> Deep sequence models [6] and full copula-based dynamic feature "
    "selection [3] are not implemented, and are labelled as future work rather "
    "than approximated."))

body.append(SEC("VI", "Conclusion"))
body.append(P(
    "We reconciled six solar-forecasting studies into one platform and used it to "
    "price three evaluation choices that the literature generally leaves unpriced. "
    "Random splitting of autocorrelated hourly data understates RMSE by 11.6% and "
    "overstates R<super>2</super> by 0.027. Hourly reanalysis irradiance is "
    "labelled at the end of its averaging interval, and ignoring this produces 264 "
    "physically impossible observations per year at a single site. A nominal 80% "
    "prediction interval from uncalibrated quantile regression covered 66.3% of "
    "observations, which conformal calibration restored to 80.2% across every "
    "weather regime. We further showed that permutation importance is a statement "
    "about a target rather than about solar energy, reconciling two published "
    "rankings, and that a scenario response can hide two large opposing pathways.",
    "body0"))
body.append(P(
    "Future work is field validation against metered generation, which is the one "
    "thing that would let accuracy claims be made at all; multi-site replication "
    "to establish how the effect sizes vary with climate; and extension to the "
    "deep sequence models the corpus identifies but this work does not implement."))

body.append(SEC("", "Reproducibility"))
body.append(P(
    "The platform, the reproducibility manifest, and the interval calibration "
    "script used for Table 1 accompany this submission. All meteorological inputs "
    "come from a keyless public API, so every experiment can be repeated at "
    "arbitrary coordinates without credentials or a data-use agreement.", "body0"))

body.append(SEC("", "Acknowledgment"))
body.append(P(
    "Weather and solar-resource data are provided by Open-Meteo under CC-BY 4.0; "
    "ERA5 is &#169; ECMWF/Copernicus.", "body0"))

# ------------------------------------------------------------- references
body.append(SEC("", "References"))
REFS = [
    "R. Hobbs and S. Joshi, &#8220;Using open-source forecasts for solar plant "
    "maintenance outage scheduling can reduce lost energy,&#8221; <i>IEEE J. "
    "Photovolt.</i>, 2026, accepted for publication.",
    "T. Mabodi and J. Hammujuddy, &#8220;Solar irradiance forecasting for informed "
    "solar systems design and financing decisions,&#8221; <i>SAIEE Africa Res. "
    "J.</i>, vol. 115, no. 3, 2024.",
    "Y. Lyu and S. Eftekharnejad, &#8220;Probabilistic solar generation "
    "forecasting for rapidly changing weather conditions,&#8221; <i>IEEE "
    "Access</i>, vol. 12, 2024.",
    "J. Rosales Huamani, U. Rojas Villanueva, C. L. Rosales Ventocilla, J. L. "
    "Castillo Sequera, and J. M. G&#243;mez Pulido, &#8220;Efficient machine "
    "learning models for solar radiation prediction using ensemble techniques: A "
    "case study in low-rainfall arid climates,&#8221; <i>IEEE Access</i>, vol. 13, "
    "2025.",
    "K. Vijay Babu <i>et al.</i>, &#8220;Solar energy forecasting using machine "
    "learning techniques for enhanced grid stability,&#8221; <i>IEEE Access</i>, "
    "vol. 13, 2025.",
    "M. Hayajneh <i>et al.</i>, &#8220;Intelligent solar forecasts: Modern ML "
    "models and TinyML role for improved solar energy yield "
    "predictions,&#8221; <i>IEEE Access</i>, vol. 12, 2024.",
    "H. Hersbach <i>et al.</i>, &#8220;The ERA5 global reanalysis,&#8221; <i>Q. J. "
    "R. Meteorol. Soc.</i>, vol. 146, no. 730, pp. 1999&#8211;2049, 2020.",
    "P. Zippenfenig, &#8220;Open-Meteo.com weather API,&#8221; 2023. [Online]. "
    "Available: https://open-meteo.com",
    "L. Breiman, &#8220;Random forests,&#8221; <i>Mach. Learn.</i>, vol. 45, "
    "no. 1, pp. 5&#8211;32, 2001.",
    "P. Geurts, D. Ernst, and L. Wehenkel, &#8220;Extremely randomized "
    "trees,&#8221; <i>Mach. Learn.</i>, vol. 63, no. 1, pp. 3&#8211;42, 2006.",
    "G. Ke <i>et al.</i>, &#8220;LightGBM: A highly efficient gradient boosting "
    "decision tree,&#8221; in <i>Proc. Adv. Neural Inf. Process. Syst.</i>, "
    "vol. 30, 2017.",
    "D. H. Wolpert, &#8220;Stacked generalization,&#8221; <i>Neural Netw.</i>, "
    "vol. 5, no. 2, pp. 241&#8211;259, 1992.",
    "A. E. Hoerl and R. W. Kennard, &#8220;Ridge regression: Biased estimation for "
    "nonorthogonal problems,&#8221; <i>Technometrics</i>, vol. 12, no. 1, "
    "pp. 55&#8211;67, 1970.",
    "Y. Romano, E. Patterson, and E. Cand&#232;s, &#8220;Conformalized quantile "
    "regression,&#8221; in <i>Proc. Adv. Neural Inf. Process. Syst.</i>, vol. 32, "
    "2019.",
    "T. Gneiting and A. E. Raftery, &#8220;Strictly proper scoring rules, "
    "prediction, and estimation,&#8221; <i>J. Amer. Statist. Assoc.</i>, vol. 102, "
    "no. 477, pp. 359&#8211;378, 2007.",
    "D. G. Erbs, S. A. Klein, and J. A. Duffie, &#8220;Estimation of the diffuse "
    "radiation fraction for hourly, daily and monthly-average global "
    "radiation,&#8221; <i>Solar Energy</i>, vol. 28, no. 4, pp. 293&#8211;302, "
    "1982.",
    "J. A. Duffie and W. A. Beckman, <i>Solar Engineering of Thermal "
    "Processes</i>, 4th ed. Hoboken, NJ, USA: Wiley, 2013.",
    "D. Faiman, &#8220;Assessing the outdoor operating temperature of photovoltaic "
    "modules,&#8221; <i>Prog. Photovolt.</i>, vol. 16, no. 4, pp. 307&#8211;315, "
    "2008.",
    "A. P. Dobos, &#8220;PVWatts version 5 manual,&#8221; Nat. Renewable Energy "
    "Lab., Golden, CO, USA, Tech. Rep. NREL/TP-6A20-62641, 2014.",
    "B. Haurwitz, &#8220;Insolation in relation to cloudiness and cloud "
    "density,&#8221; <i>J. Meteorol.</i>, vol. 2, no. 1, pp. 1&#8211;8, 1945.",
    "F. Pedregosa <i>et al.</i>, &#8220;Scikit-learn: Machine learning in "
    "Python,&#8221; <i>J. Mach. Learn. Res.</i>, vol. 12, pp. 2825&#8211;2830, "
    "2011.",
]
for i, r in enumerate(REFS, 1):
    body.append(Paragraph("[%d] %s" % (i, r), S["ref"]))

# --------------------------------------------------------------- biographies
body.append(Spacer(1, 8))
BIO_STUB = ("&lt;ADD BIOGRAPHY: degree(s) received, institution, year, current "
            "role, and research interests. Two to four sentences.&gt;")
for nm in ["T. HARSHINI SOWMYA", "M. LAVANYA DURGA", "P. J. S. SIDDHARTHA",
           "M. AJAY PRAKASH", "P. MARUTHI SREERAM", "K. SURYA PRAKASH"]:
    body.append(bio(nm, BIO_STUB))
body.append(Paragraph('<para alignment="right">'
                      '<font color="#0073AE" size="11">&#9679; &#9679; &#9679;</font>'
                      '</para>', S["body0"]))


# ==================================================================== canvas
def _footer(c, page_no, first):
    """Production footers. Published mode only."""
    c.saveState()
    c.setFont("Tm", 7.6)
    c.setFillColor(BLACK)
    y = 24
    if first:
        c.drawString(LM, y, "<PAGE>")
        c.drawRightString(PW - RM, y, "VOLUME <VOL>, <YEAR>")
        c.setFont("Tm", 6.8)
        c.drawCentredString(PW / 2, y + 11,
                            "© <YEAR> The Authors. This work is licensed "
                            "under a Creative Commons Attribution 4.0 License.")
        c.drawCentredString(PW / 2, y + 3.5,
                            "For more information, see "
                            "https://creativecommons.org/licenses/by/4.0/")
    else:
        c.drawString(LM, y, "VOLUME <VOL>, <YEAR>")
        c.drawRightString(PW - RM, y, "<PAGE>")
    c.restoreState()


def _ms_page_number(c, doc):
    """Plain sequential page number - the only furniture a manuscript carries."""
    c.saveState()
    c.setFont("Tm", 8.5)
    c.setFillColor(BLACK)
    c.drawCentredString(PW / 2, 26, str(doc.page))
    c.restoreState()


def on_first(c, doc):
    if PUBLISHED:
        access_logo(c, LM, PH - 44, scale=1.0)
        c.setStrokeColor(colors.HexColor("#666666"))
        c.setLineWidth(0.7)
        c.line(LM, PH - 56, PW - RM, PH - 56)
        _footer(c, doc.page, True)
    else:
        _ms_page_number(c, doc)


def on_later(c, doc):
    c.saveState()
    c.setFont("Tm", 7.4)
    c.setFillColor(BLACK)
    c.drawString(LM, PH - 30, RUNNING_HEAD)
    if PUBLISHED:
        access_logo(c, PW - RM - 78, PH - 34, scale=0.62, tagline=False)
    c.setStrokeColor(colors.HexColor("#666666"))
    c.setLineWidth(0.7)
    c.line(LM, PH - 39, PW - RM, PH - 39)
    c.restoreState()
    if PUBLISHED:
        _footer(c, doc.page, False)
    else:
        _ms_page_number(c, doc)


doc = BaseDocTemplate(
    OUTFILE, pagesize=(PW, PH),
    leftMargin=LM, rightMargin=RM, topMargin=BODY_TOP, bottomMargin=BODY_BOT,
    title="Quantifying Three Evaluation Pitfalls in Machine-Learning Solar "
          "Forecasting",
    author="T. Harshini Sowmya et al.",
    subject="IEEE Access format draft",
)

# measure the front matter so the two-column region starts exactly below it
fm_h = 0
for f in front:
    w, h = f.wrap(PW - LM - RM, PH)
    fm_h += h + getattr(f, "getSpaceBefore", lambda: 0)() \
             + getattr(f, "getSpaceAfter", lambda: 0)()
fm_h = min(fm_h + 10, PH - BODY_BOT - 120)

f_front = Frame(LM, PH - BODY_TOP - fm_h, PW - LM - RM, fm_h,
                leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
                id="front")
f_c1 = Frame(LM, BODY_BOT, COLW, BODY_H - fm_h,
             leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
             id="c1")
f_c2 = Frame(LM + COLW + GUT, BODY_BOT, COLW, BODY_H - fm_h,
             leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
             id="c2")
f_l1 = Frame(LM, BODY_BOT, COLW, BODY_H,
             leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
             id="l1")
f_l2 = Frame(LM + COLW + GUT, BODY_BOT, COLW, BODY_H,
             leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
             id="l2")

doc.addPageTemplates([
    PageTemplate(id="first", frames=[f_front, f_c1, f_c2], onPage=on_first),
    PageTemplate(id="later", frames=[f_l1, f_l2], onPage=on_later),
])

story = list(front) + [NextPageTemplate("later")] + body
doc.build(story)
print("Saved to", OUTFILE)
