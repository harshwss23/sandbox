# Electricity Price Forecasting & Model Governance Workspace

## Project Overview
This repository contains the experimental pipeline, historical telemetry, model predictions, evaluation metrics, and governance policies for day-ahead electricity price forecasting across wholesale delivery hubs (NP15, SP15, ZP26).

The research pipeline tracks multiple model families across three consecutive operating years, incorporating seasonal merit-order interactions, fuel costs, renewable penetration dynamics, and structural market-regime shifts.

All observations in this workspace originate from a calibrated, reproducible simulation process designed to emulate wholesale electricity spot markets (locational marginal pricing with jump-diffusion spike processes and stochastic volatility). This dataset is simulated for algorithmic validation and does not represent real historical utility data.

---

## Directory Architecture

```
electricity_deployment_review_workspace/
├── prompt.md                           # Formal deployment review mandate
├── README.md                           # System documentation and directory index
├── configs/
│   ├── data_config.yaml                # Simulation, calendar, and temporal split specifications
│   ├── model_selection_policy.yaml     # Governance standards: selection rules & deployment gates
│   ├── ridge.yaml                      # Regularized linear model configuration
│   ├── random_forest.yaml              # Random Forest regressor configuration
│   └── hist_gradient_boosting.yaml     # HistGradientBoosting regressor configuration
├── data/
│   ├── market_clearing_observations.csv# Full 26,280-hour market clearing dataset
│   ├── dataset_manifest.csv            # Summary statistics, columns, and data types
│   ├── split_manifest.csv              # Audit manifest of temporal splits
│   └── regime_thresholds.csv           # Causal training thresholds and ex-post reference thresholds
├── src/
│   ├── generate_data.py                # Wholesale spot market stochastic simulator
│   ├── features.py                     # Causal feature engineering and lag construction
│   ├── models.py                       # Estimator wrappers (Persistence, Ridge, RF, HGBR)
│   ├── evaluate.py                     # Loss functions and grouping routines
│   ├── spike_metrics.py                # Tail evaluation and spike classification routines
│   ├── bootstrap.py                    # Moving block and naive resampling implementations
│   └── run_pipeline.py                 # Master reproduction pipeline
├── predictions/
│   ├── persistence_test.csv            # Test partition predictions: Persistence
│   ├── ridge_test.csv                  # Test partition predictions: Ridge
│   ├── random_forest_test.csv          # Test partition predictions: Random Forest
│   └── hist_gradient_boosting_test.csv # Test partition predictions: HistGradientBoosting
├── results/
│   ├── model_selection_validation.csv  # Candidate validation metrics across policy rules
│   ├── test_phase_metrics_eligible.csv # Governing phase performance on commercial delivery contracts
│   ├── test_phase_metrics_pooled.csv   # Broad operational population performance
│   ├── shifted_zonal_metrics.csv       # Zonal delivery hub breakdown during shifted operations
│   ├── shifted_regime_metrics.csv      # Operational regime breakdown (NORMAL, VOLATILE, SPIKE)
│   ├── shifted_zone_regime_metrics.csv # Cross-tabulated zonal x regime cell degradation
│   ├── shifted_spike_metrics.csv       # Shifted interval spike classification & conditional errors
│   ├── shifted_macro_spike_metrics.csv # Macro-averaged vs micro-averaged zonal spike sensitivities
│   └── bootstrap_uncertainty_comparison.csv # Moving block vs IID bootstrap comparison
├── operations/
│   ├── trading_desk_runbook.md         # Operational procedures, contract eligibility, and protocols
│   ├── data_dictionary.md              # Column schemas, contract definitions, and telemetry flags
│   └── dispatch_telemetry_audit.log    # Operational log of non-firm overrides and telemetry incidents
├── notes/
│   ├── experiment_log.md               # Historical log of pipeline runs and version milestones
│   ├── governance_meeting_minutes.md   # Model risk governance deliberations and policy revisions
│   ├── methodology_notes.md            # Mathematical formulas, loss functions, and bootstrap theory
│   ├── zonal_composition_memo.md       # Risk memo analyzing renewable buildout and volume shifts
│   └── known_limitations.md            # Documented operational edge cases and modeling constraints
└── archive/
    ├── preliminary_metrics.csv         # Vintage 1 development benchmarks (base features)
    └── early_experiment_notes.md       # Scientific rationale for feature expansion
```

---

## Experimental & Temporal Framework
The 3-year timeline ($N = 26,280$ consecutive hours) is chronologically partitioned into:
- **Year 1 (Train)**: Hours $0 \dots 8,759$ ($n = 8,760$). Baseline model training and causal threshold estimation.
- **Year 2 (Validation)**: Hours $8,760 \dots 17,519$ ($n = 8,760$). Predeclared candidate model selection.
- **Year 3 H1 (Test Pre-Shift)**: Hours $17,520 \dots 21,899$ ($n = 4,380$). Pre-shift baseline testing.
- **Year 3 H2 (Test Shifted)**: Hours $21,900 \dots 26,279$ ($n = 4,380$). Post-shift assessment under elevated fuel volatility, carbon compliance pricing, and solar expansion.

---

## Reproduction Instructions
All results can be reproduced directly via:
```bash
python src/run_pipeline.py
```
Outputs are serialized into `data/`, `predictions/`, `results/`, and `archive/`.
