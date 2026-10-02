# Documented System Limitations & Modeling Caveats

## 1. Tree Ensemble Boundedness on Extreme Spot Spikes
Both Random Forest and HistGradientBoosting partition input feature space into hyper-rectangles and predict constant conditional means within leaf nodes.
- **Limitation**: When a structural distribution shift introduces novel clearing price levels beyond the maximum observed in the training split, standard decision trees cannot extrapolate above historical training maxima.
- **Empirical Consequence**: Tree models systematically under-predict peak price spikes, yielding validation spike recalls of only 10.47% (Random Forest) and 7.28% (HistGradientBoosting), leading to their immediate disqualification under Rule 2 of the predeclared selection policy.

## 2. Inappropriate Post-Selection Re-Optimization
A common pitfall in retrospective analytics is re-evaluating the model selection tournament directly on the shifted test period.
- **Trap**: An analyst inspecting Year 3 H2 metrics might observe that HistGradientBoosting achieves a lower overall WMAPE on certain shifted subgroups, or that Random Forest performs slightly better in specific volatile regimes.
- **Governance Constraint**: Model risk policies strictly prohibit retrospective model substitution. Once a model is selected under a predeclared protocol on validation data, the deployment review must evaluate that specific candidate's survivability under post-shift stress.

## 3. Telemetry Cleaning vs Operational Standby Overrides
Emergency standby contracts represent out-of-market settlements. Attempting to improve candidate metrics by pooling all operational observations back into the test sample introduces severe regulatory penalty bias and invalidates commercial compliance.
