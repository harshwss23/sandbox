# Pipeline Execution Log

## Run Milestones

### Milestone 001: Vintage 1 Baseline Run (Initial Pipeline)
- **Execution Date**: 2024-11-15
- **Configuration**: Feature set `base_no_interaction` (autoregressive price lags, rolling 24h mean/std, linear fuel and load).
- **Target Partition**: Year 2 Validation Set ($n = 8,760$).
- **Output Artifact**: `archive/preliminary_metrics.csv`
- **Context**: Evaluated basic feasibility of autoregressive linear and tree-based benchmarks. While models produced lower aggregate RMSE than persistence, residual diagnostics revealed severe convex bias during peak demand ramping hours.

### Milestone 002: Production Candidate Specification (Feature Expansion)
- **Execution Date**: 2024-12-20
- **Configuration**: Upgraded to `full_operational_v2`. Added quadratic net load (`net_load_squared`), fuel-heat rate interaction, and non-linear heating/cooling degree days.
- **Predeclared Policy Locked**: Registered `configs/model_selection_policy.yaml` (Document ID: `POL-ETRA-2025-V2`) with the Model Risk Governance Committee prior to unblinding Year 3 data.
- **Validation Run Results**: Recorded in `results/model_selection_validation.csv`.
  - Persistence: WMAPE = 0.1596 (Fails Rule 1).
  - Ridge (`ridge_reg_v1`): WMAPE = 0.1306, Spike Recall = 0.1639, Volatile Degradation Ratio = -0.2519. Eligible.
  - RandomForest (`random_forest_v1`): WMAPE = 0.1391, Spike Recall = 0.1047 (Fails Rule 2: $0.1047 < 0.150$). Disqualified.
  - HistGradientBoosting (`hist_gradient_boosting_v1`): WMAPE = 0.1355, Spike Recall = 0.0728 (Fails Rule 2: $0.0728 < 0.150$). Disqualified.

### Milestone 003: Post-Shift Evaluation & Deployment Review
- **Execution Date**: 2025-12-31
- **Target Partition**: Year 3 H1 (Pre-Shift, $n = 4,380$) and Year 3 H2 (Shifted, $n = 4,380$).
- **Focus**: Assess the behavior of the selected candidate under the Year 3 H2 distribution shift across mandatory deployment gates (improvement over persistence, spike recall, zonal stability, bootstrap confidence intervals).
- **Artifacts Generated**:
  - `results/test_phase_metrics_eligible.csv`
  - `results/test_phase_metrics_pooled.csv`
  - `results/shifted_zonal_metrics.csv`
  - `results/shifted_regime_metrics.csv`
  - `results/shifted_zone_regime_metrics.csv`
  - `results/shifted_spike_metrics.csv`
  - `results/shifted_macro_spike_metrics.csv`
  - `results/bootstrap_uncertainty_comparison.csv`
