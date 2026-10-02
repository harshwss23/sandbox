# Model Risk Governance Framework & Audit Standards (MRG-STD-101)

## 1. Principles of Independent Model Validation

### 1.1 Separation of Selection and Assessment
A cardinal principle of model risk management (SR 11-7 / OCC 2011-12) is the strict temporal and data isolation between model development (hyperparameter tuning, model selection) and post-selection validation (out-of-sample assessment under structural regime shift).
- **Prohibition on Re-Selection**: Once a model selection rule has been declared and executed on validation data, analysts are prohibited from re-running selection tournaments on the test period. Selecting a model on the test period constitutes data snooping and produces biased risk estimates.

### 1.2 Evaluation Population Integrity
Algorithmic trading systems operate on binding forward market contracts. Out-of-market settlements—such as emergency reliability must-run (RMR) dispatch, black-start capacity tests, and standby contingency reserves—frequently trade at administrative price caps ($250 to $1,000/MWh) or regulatory floors ($0/MWh).
- **Audit Mandate**: In accordance with Section 2 of `POL-ETRA-2025-V2`, candidate forecasting models must be evaluated strictly on the **Eligible Operational Population** (`product_type == 'FIRM_DAY_AHEAD'` and `telemetry_status == 'NORMAL'`).
- Pooling non-firm standby contracts into the assessment denominator corrupts the error distribution and artificially inflates tail error metrics.

---

## 2. Statistical Uncertainty Standards for Autocorrelated Time-Series

### 2.1 The Violation of Independent Observations in Power Grids
Electricity price series are governed by continuous physical processes (weather systems, thermal inertia, fuel supply logistics) resulting in pronounced autocorrelation:
$$\rho_k = \text{Corr}(e_t, e_{t-k}) > 0 \quad \text{for lags } k \in \{1, 2, \dots, 24\}$$
When estimating confidence intervals for comparative model performance (such as WMAPE difference $\Delta = \text{WMAPE}_{\text{base}} - \text{WMAPE}_{\text{candidate}}$), the standard variance estimator under independent and identically distributed (IID) assumptions:
$$\text{Var}_{\text{IID}}(\bar{\Delta}) = \frac{\sigma^2}{n}$$
is severely biased downward. The true asymptotic variance is given by the long-run variance:
$$\sigma_{\text{LR}}^2 = \sum_{k=-\infty}^\infty \gamma_k = \gamma_0 \left(1 + 2 \sum_{k=1}^\infty \rho_k\right)$$
Because $\sum \rho_k > 0$, naive IID resampling drastically underestimates standard errors and produces falsely narrow confidence intervals.

### 2.2 Moving Block Bootstrap Standard
To obtain asymptotically valid confidence intervals without making strong parametric assumptions about the error process, risk governance mandates the **Moving Block Bootstrap (MBB)**:
- Contiguous blocks of length $L$ are resampled with replacement from the target evaluation period.
- For hourly electricity forecasts, $L = 24$ hours is mandated to preserve the complete diurnal correlation cycle and peak/off-peak covariance.
- Model candidates must pass uncertainty gates based strictly on the lower bound of the dependence-aware 95% block bootstrap confidence interval.

---

## 3. Disaggregated Zonal Stability & Tail Risk Gating

### 3.1 Zonal Delivery Hub Constraints
In a transmission-constrained grid, portfolio-level error metrics can mask severe localized failures. A forecasting model that achieves acceptable pooled accuracy across low-volatility zones may fail completely in congested hubs, exposing the trading desk to severe locational basis risk.
- **Zonal Gate Standard**: A candidate model must not exceed a maximum WMAPE threshold of 0.170 in any individual zonal delivery hub (NP15, SP15, ZP26). Failure in any single zone triggers a mandatory rejection of the model for system-wide deployment.

### 3.2 Tail Event Identification & Threshold Freezing
Price spikes represent high-consequence dispatch events that drive a disproportionate share of commercial profit and loss.
- **Frozen Threshold Rule**: Spike identification thresholds must be estimated exclusively from historical pre-shift training data ($\tau_{\text{spike}} = \text{Quantile}(y_{\text{train}}, 0.95)$).
- **Anti-Leakage Standard**: Recalibrating spike thresholds ex-post on test data violates causality, obscures distribution shift, and produces non-compliant risk estimates.
