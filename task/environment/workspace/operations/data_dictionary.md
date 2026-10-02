# Wholesale Market Telemetry & Schema Dictionary

## Table: `market_clearing_observations.csv`

| Column Name | Storage Type | Description | Operational Domain | Governance Filter Rule |
| :--- | :--- | :--- | :--- | :--- |
| `timestamp` | Timestamp (`YYYY-MM-DD HH:MM:SS`) | Hourly dispatch beginning timestamp (America/Los_Angeles). | Temporal index | Strictly ordered; no gaps |
| `zone` | Categorical String (`NP15`, `SP15`, `ZP26`) | Wholesale trading hub / delivery basin. | Zonal delivery | All 3 zones active |
| `product_type` | Categorical String (`FIRM_DAY_AHEAD`, `STANDBY_RESERVE`) | Market clearing product contract specification. | Settlement | Only `FIRM_DAY_AHEAD` is eligible for model approval |
| `telemetry_status` | Categorical String (`NORMAL`, `ESTIMATED`, `MAINTENANCE`) | EMS data feed integrity indicator. | Data engineering | Only `NORMAL` is eligible for model approval |
| `demand_mw` | Numeric Float | Scheduled system load forecast for the delivery hour (MW). | Exogenous driver | Known prior to day-ahead gate closure |
| `renewable_generation_mw` | Numeric Float | Forecasted utility-scale solar and wind generation (MW). | Exogenous driver | Day-ahead meteorological forecast |
| `temperature_c` | Numeric Float | Population-weighted zonal ambient dry-bulb temperature (°C). | Exogenous weather | Numerical weather prediction (NWP) |
| `fuel_index_usd_mmbtu` | Numeric Float | Regional natural gas spot benchmark index ($/MMBtu). | Exogenous fuel | Published at 09:00 Pacific day-ahead |
| `hour` | Integer (`0` to `23`) | Hour of day (local standard). | Calendar | Cyclical predictor |
| `day_of_week` | Integer (`0` = Monday to `6` = Sunday) | Day of week. | Calendar | Weekly cycle |
| `weekend_flag` | Binary Integer (`0` or `1`) | 1 if Saturday or Sunday; 0 otherwise. | Calendar | Tariff scheduling flag |
| `price_usd_mwh` | Numeric Float | Realized market clearing price ($/MWh). | Modeling Target | Supervised target; strictly causal |

---

## Evaluation Population Filtering Criteria

```python
# Standard Model Governance Population Filter
is_eligible_eval = (
    (df['product_type'] == 'FIRM_DAY_AHEAD') & 
    (df['telemetry_status'] == 'NORMAL')
)
```

- Observations failing this criteria include emergency dispatch capacity and proxy estimates.
- While pooled tables (`results/test_phase_metrics_pooled.csv`) are generated for operational volume monitoring, model approval decisions must strictly reference `results/test_phase_metrics_eligible.csv`.
