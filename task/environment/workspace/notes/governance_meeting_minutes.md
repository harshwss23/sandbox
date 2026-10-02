# Model Risk Governance Committee — Meeting Minutes

**Document Ref**: MRGC-MIN-2024-Q4  
**Date**: December 22, 2024  
**Attendees**: Head of Quantitative Research, Lead Risk Officer, Senior Power Trader, Lead ML Engineer  

---

### Agenda Item 1: Review of Predeclared Selection Policy for 2025 Deployment
- The committee reviewed policy draft `POL-ETRA-2025-V2`.
- **Discussion on Spike Recall Minimum**:
  - The Trading Desk emphasized that tree ensembles have historically underperformed during unexpected net-load spikes because decision trees cannot extrapolate beyond historical training price thresholds.
  - The committee approved a strict spike sensitivity gate: candidates must achieve at least 0.15 spike recall on the validation set under the pre-shift frozen P95 threshold.
  - Models failing this sensitivity floor represent an unacceptable unhedged volumetric risk to the commercial book.

### Agenda Item 2: Telemetry Isolation & Governing Evaluation Population
- Risk Officers noted that during summer heat emergencies, grid operators declare Flex Alerts and dispatch out-of-market standby reserves.
- Standby settlements include regulatory penalty multipliers that do not reflect economic clearing fundamentals.
- **Resolution**: All model deployment reviews must isolate the `FIRM_DAY_AHEAD` contracts with `NORMAL` telemetry status. The committee explicitly mandated that broad operational pooled data must not be used for deployment gating.

### Agenda Item 3: Post-Shift Mandatory Deployment Gates
- The committee codified four mandatory gates in Section 2 of `POL-ETRA-2025-V2`:
  1. Minimum 18.0% relative WMAPE improvement over the baseline during shifted operations.
  2. Micro-averaged interval spike recall $\ge 0.28$ under the frozen pre-shift threshold.
  3. Maximum zonal WMAPE across any individual delivery hub $\le 0.170$.
  4. Lower bound of the 95% confidence interval for relative WMAPE improvement $\ge 16.60\%$, verified using dependence-aware moving block resampling.
- **Unanimous Agreement**: All four gates must be simultaneously satisfied. Any single gate failure triggers an immediate **REJECT** recommendation.
