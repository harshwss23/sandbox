# Methodology Notes: Loss Functions, Regimes & Statistical Uncertainty

## 1. Weighted Mean Absolute Percentage Error (WMAPE)
In power markets, prices regularly approach zero or turn negative due to high renewable penetration and inflexible baseload generation. Traditional MAPE has a singularity at zero:
$$\text{MAPE} = \frac{1}{N}\sum_{t=1}^N \left|\frac{y_t - \hat{y}_t}{y_t}\right| \to \infty \quad \text{as } y_t \to 0$$
To avoid this instability, the industry standard is WMAPE (also known as the MAD/Mean ratio):
$$\text{WMAPE} = \frac{\sum_{t=1}^N |y_t - \hat{y}_t|}{\sum_{t=1}^N |y_t|}$$
Relative improvement of candidate $M$ over baseline $B$ is defined as:
$$\text{RelImprovement}(\%) = \frac{\text{WMAPE}_B - \text{WMAPE}_M}{\text{WMAPE}_B} \times 100$$

---

## 2. Regime Partitioning & Causal Threshold Provenance
To avoid lookahead bias and temporal data leakage, all evaluation regime thresholds must be estimated strictly from the Year 1 Training partition ($n = 8,760$):
- **Spike Threshold**: 95th percentile of training clearing prices:
  $$\tau_{\text{spike}} = \text{Quantile}(y_{\text{train}}, 0.95) = 101.8950 \text{ \$/MWh}$$
- **Volatile Threshold**: 80th percentile of the strictly causal 24-hour rolling standard deviation of training prices:
  $$\tau_{\text{vol}} = \text{Quantile}(\sigma_{\text{roll},24}^{\text{train}}, 0.80) = 11.5170$$

### Mutually Exclusive Operational Regimes:
For each evaluation hour $t$:
1. `SPIKE`: $y_t \ge \tau_{\text{spike}}$
2. `VOLATILE`: $\sigma_{\text{roll},24}(t-1) \ge \tau_{\text{vol}}$ and not `SPIKE`
3. `NORMAL`: All remaining hours.

---

## 3. Resampling Theory: Dependence-Aware vs Naive IID Bootstrap
Electricity spot prices and model forecast errors exhibit significant serial correlation, daily diurnal cycles, and clustered volatility shocks.
- **Flaw of Naive IID Resampling**: Shuffling individual hourly observations independently destroys the temporal dependency structure $\text{Cov}(\epsilon_t, \epsilon_{t-k})$. When error differences are positively autocorrelated, naive IID resampling underestimates sample variance and produces spuriously narrow confidence intervals.
- **Moving Block Bootstrap (MBB)**: Developed by Künsch (1989) and Liu & Singh (1992), MBB resamples overlapping blocks of contiguous observations:
  $$\mathcal{B}_i = \{(\hat{y}_t, y_t), (\hat{y}_{t+1}, y_{t+1}), \dots, (\hat{y}_{t+L-1}, y_{t+L-1})\}$$
  Setting block length $L = 24$ hours preserves the full diurnal correlation structure. Per ETRA governance, all production deployment risk gates require MBB ($L = 24$, $B = 400$).
