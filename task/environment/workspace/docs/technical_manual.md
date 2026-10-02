# Technical Manual: Algorithmic Power Forecasting & Dispatch Optimization

## 1. Wholesale Electricity Market Architecture & Clearing Mechanics

### 1.1 Physical Grid Topologies and Delivery Basins
In modern deregulated wholesale power grids—exemplified by regional transmission operators (RTOs) and independent system operators (ISOs) such as the California Independent System Operator (CAISO), ERCOT, and PJM—electricity cannot be stored in large quantities at zero cost. Supply and demand must remain continuously in instantaneous equilibrium at 60 Hz system frequency. Consequently, the clearing price of electricity is determined via locational marginal pricing (LMP), which decomposes the cost of delivering an incremental megawatt-hour (MWh) of electrical energy into three additive components:
$$\text{LMP}_{i,t} = \lambda_{\text{energy},t} + \mu_{\text{congestion},i,t} + \gamma_{\text{loss},i,t}$$
where:
- $\lambda_{\text{energy},t}$ represents the system-wide shadow price of unconstrained marginal energy;
- $\mu_{\text{congestion},i,t}$ reflects the marginal transmission congestion penalty or relief associated with physical branch thermal limits into delivery node $i$;
- $\gamma_{\text{loss},i,t}$ represents the marginal resistive transmission heat loss factor relative to the system reference slack bus.

### 1.2 Zonal Hub Aggregations
To support bilateral forward contracting, derivative hedging, and day-ahead financial scheduling, thousands of individual nodal pricing points are aggregated into major commercial trading hubs:
1. **NP15 (North of Path 15)**: Encompasses Northern California load centers (San Francisco Bay Area, Sacramento Valley) and upper Sierra hydroelectric cascades. Characterized by seasonal snowmelt run-of-river generation, thermal natural gas peakers, and intertie imports from the Pacific Northwest (BPA).
2. **SP15 (South of Path 15)**: Represents the dense Southern California metropolitan load basin (Los Angeles, Orange County, San Diego). Predominantly driven by coastal gas-fired combined-cycle plants, extensive rooftop photovoltaic systems, and imports across the Desert Southwest interties.
3. **ZP26 (Zone Path 26)**: Covers the Central San Joaquin Valley transition corridor. Dominated by utility-scale solar photovoltaic generation and high-voltage transmission bottlenecks connecting Northern and Southern California.

---

## 2. Theoretical Merit-Order Economics & Convexity

### 2.1 The Economic Dispatch Stack
The foundational microeconomic mechanism driving wholesale electricity spot prices is the merit-order dispatch curve. Thermal generation assets bid their incremental heat rates multiplied by their fuel costs:
$$\text{Marginal Cost}_j = \text{Heat Rate}_j \times P_{\text{gas}} + \text{VOM}_j + \text{Emission Cost}_j$$
where:
- $\text{Heat Rate}_j$ represents thermal fuel consumption efficiency in MMBtu/MWh (ranging from ~6.8 MMBtu/MWh for modern Combined-Cycle Gas Turbines to >12.5 MMBtu/MWh for aeroderivative peaking turbines);
- $P_{\text{gas}}$ represents delivered fuel price at citygate hubs (SoCal Citygate, PG&E Citygate);
- $\text{VOM}_j$ denotes variable operation and maintenance expense;
- $\text{Emission Cost}_j = \text{Heat Rate}_j \times \text{Emission Factor}_j \times P_{\text{carbon}}$ incorporates greenhouse gas allowance compliance (e.g. California Cap-and-Trade / WCI allowances).

### 2.2 Quadratic Ramping and Merit-Order Convexity
As net system load ($L_{\text{net}} = \text{Demand} - \text{Renewables}$) increases, baseload combined-cycle units reach maximum capacity. System operators must dispatch increasingly inefficient, fast-ramping simple-cycle peakers. This produces an intrinsically non-linear, convex cost curve:
$$C(L_{\text{net}}) = \alpha + \beta_1 L_{\text{net}} + \beta_2 L_{\text{net}}^2 + \epsilon_t$$
Models that omit polynomial net-load interactions suffer severe structural bias during high net-load ramp intervals.

---

## 3. Machine Learning Architectures for Spot Price Forecasting

### 3.1 Regularized Linear Estimators (Ridge Regression)
Ridge regression minimizes the penalized residual sum of squares:
$$\min_{\beta} \|y - X\beta\|_2^2 + \alpha \|\beta\|_2^2$$
When augmented with explicit polynomial interaction terms ($\text{net\_load}^2$, $\text{fuel} \times \text{net\_load}$, degree-day thresholds), Ridge regression maintains linear extrapolation capability along extreme demand slopes. Unlike decision tree ensembles, which clip predictions at historical leaf bounds, a regularized linear model can predict previously unobserved price levels when underlying fuel or load drivers reach new extremes.

### 3.2 Decision Tree Ensembles & Leaf Boundedness
Tree ensembles (Random Forest, Gradient Boosted Trees) recursively partition feature space into orthogonal hyperplanes:
$$\hat{f}(x) = \sum_{m=1}^M c_m \mathbb{I}(x \in R_m)$$
Because the prediction in each leaf $R_m$ is bounded by the training observations contained within it:
$$\hat{y}(x) \le \max_{i \in \text{Train}} y_i \quad \forall x$$
During an out-of-distribution regime shift where actual clearing prices exceed historical training levels, tree ensembles fail to predict the magnitude of price spikes, resulting in a collapse in spike recall.

---

## 4. Quantitative Metrics and Governance Benchmarks

### 4.1 Loss Function Sensitivity
- **MAE vs RMSE**: MAE evaluates the median conditional expectation under Laplace error assumptions, while RMSE penalizes large errors quadratically.
- **WMAPE (Weighted Mean Absolute Percentage Error)**:
  $$\text{WMAPE} = \frac{\sum |y_t - \hat{y}_t|}{\sum |y_t|}$$
  Unlike MAPE, which divides by $y_t$ directly and explodes when prices drop toward zero or become negative, WMAPE is numerically stable and volume-weighted.

### 4.2 Simpson's Paradox in Market Analytics
When evaluating multi-zonal power portfolios across distinct operating periods, aggregate metric improvements can mask severe localized failures. Specifically, if volume weights shift toward more predictable or less volatile delivery basins, the portfolio-wide error metric may appear satisfactory while specific critical zones experience catastrophic degradation. Formal model governance requires evaluating disaggregated zonal performance to ensure reliability across all market participants.
