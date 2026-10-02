# Trading Desk Standard Operating Runbook (ETRA-SOP-402)

## 1. Scope & Application
This runbook governs the day-ahead commercial bidding, scheduling, and risk valuation workflows across the California and Western Interconnection wholesale delivery nodes (NP15, SP15, ZP26).

## 2. Product Classifications & Settlement Boundaries

### 2.1 FIRM_DAY_AHEAD (Core Commercial Contracts)
- **Definition**: Financially binding, physical forward power delivery scheduled in the Day-Ahead Market (DAM) with full locational marginal price (LMP) settlement.
- **Contract Integrity**: Subject to standard bilateral credit terms, strict scheduling coordinator (SC) timelines, and regulatory performance penalties.
- **Model Evaluation Role**: Represents the official commercial evaluation population for all algorithmic forecasting gates and production deployment approvals under `POL-ETRA-2025-V2`.

### 2.2 STANDBY_RESERVE (Emergency Operational Capacity)
- **Definition**: Contingency spinning and non-spinning reserves procured by the balancing authority for system reliability emergencies.
- **Settlement Nature**: Subject to administrative penalty overrides, mandatory dispatch orders, and out-of-market emergency pricing during flex alerts.
- **Governance Requirement**: Because standby capacity incurs artificial administrative price caps and dispatch floors unrelated to economic merit-order clearing, standby observations **must never be pooled with core commercial delivery data** for production model authorization.
- **Operational Reality**: Operations desks track standby volume for reserve-adequacy monitoring; however, risk governance strictly isolates firm commercial settlements.

## 3. Data Telemetry & Quality Standards

### 3.1 Telemetry Quality Flags
- `NORMAL`: Verified electronic telemetry from automated metering infrastructure (AMI) and balancing authority energy management systems (EMS).
- `ESTIMATED`: Unverified proxy settlements generated during supervisory control and data acquisition (SCADA) network drops or state-estimator convergence lag.
- `MAINTENANCE`: Substation testing or transducer recalibration intervals.

### 3.2 Evaluation Clean-Case Rule
Per Section 2 of `POL-ETRA-2025-V2`, the **Eligible Operational Population** requires:
$$\text{product\_type} == \text{'FIRM\_DAY\_AHEAD'} \quad \text{AND} \quad \text{telemetry\_status} == \text{'NORMAL'}$$

Any candidate evaluation conducted on the unweighted pooled telemetry population (`POOLED_OPERATIONAL`) suffers from non-firm settlement distortion and is disqualified from executive sign-off.
