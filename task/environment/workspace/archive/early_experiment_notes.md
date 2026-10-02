# Historical Development Notes: Vintage 1 Feasibility Study

**Vintage Tag**: `preliminary_v1`  
**Associated Artifact**: `archive/preliminary_metrics.csv`  
**Feature Architecture**: `base_no_interaction`  

---

### 1. Scope of Initial Milestone
During Q3 2024, our preliminary development sprint evaluated initial baseline models on the Year 2 Validation partition using standard linear lags and weather inputs:
- Exogenous linear load (`demand_mw`), wind/solar (`renewable_generation_mw`), ambient temperature (`temperature_c`), and fuel index (`fuel_index_usd_mmbtu`).
- Autoregressive lags ($t-1, t-2, t-24, t-168$).
- Shifted 24-hour rolling mean and standard deviation.

### 2. Omitted Features in Vintage 1
At this early development stage, several critical physical and financial non-linearities were not yet implemented:
- **Net Load Convexity**: Power plants are dispatched in increasing order of heat rate; as net load exceeds 280 MW, peaking units create a steep non-linear quadratic price curve (`net_load_squared`).
- **Fuel-Heat Interaction**: Marginal generator costs depend on the product of generator heat rate and gas price (`fuel_heat_interaction`).
- **Degree-Day Non-Linearity**: Temperature elasticity accelerates non-linearly during extreme cooling degree days.

### 3. Conclusion & Archival Rationale
The preliminary numbers recorded in `archive/preliminary_metrics.csv` provided proof-of-concept that machine learning models could outperform the naive persistence benchmark. However, because Vintage 1 omitted quadratic supply-stack terms, all models exhibited significant residual under-prediction during net-load ramp events. Vintage 1 was subsequently superseded by `full_operational_v2`.
