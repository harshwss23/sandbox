import os
import yaml
import numpy as np
import pandas as pd

def generate_power_market_dataset(config_path="configs/data_config.yaml", output_path="data/market_clearing_observations.csv"):
    with open(config_path, "r") as f:
        cfg = yaml.safe_load(f)
        
    seed = cfg.get("seed", 101)
    np.random.seed(seed)
    
    n_hours = cfg.get("total_hours", 26280)
    start_ts = cfg.get("start_timestamp", "2023-01-01 00:00:00")
    timestamps = pd.date_range(start_ts, periods=n_hours, freq="h")
    
    # Exogenous weather & calendar
    doy = timestamps.dayofyear.values
    hod = timestamps.hour.values
    dow = timestamps.dayofweek.values
    is_weekend = (dow >= 5).astype(int)
    
    # Fuel & Exogenous drivers
    # Base natural gas benchmark ($/MMBtu)
    gas_base = cfg["simulation_parameters"]["base_gas_price_mmbtu"] + 0.75 * np.sin(2 * np.pi * doy / 365.25)
    gas_rw = np.cumsum(np.random.normal(0, 0.02, size=n_hours))
    
    # In shifted period (final 4380 hours), structural shift occurs:
    # 1. Natural gas adder + carbon compliance adder
    gas_shift = np.zeros(n_hours)
    gas_shift[21900:] = (
        cfg["simulation_parameters"]["shifted_gas_price_adder"] 
        + cfg["simulation_parameters"]["carbon_price_adder_shifted"] 
        + np.cumsum(np.random.normal(0, 0.025, size=4380))
    )
    gas_price = np.maximum(2.20, gas_base + gas_rw + gas_shift)
    
    # Temperature (°C)
    temp_seasonal = 16.5 - 8.5 * np.cos(2 * np.pi * doy / 365.25) + 5.2 * np.sin(2 * np.pi * (hod - 8) / 24)
    temp_ar = np.zeros(n_hours)
    t_val = 0.0
    for t in range(n_hours):
        t_val = 0.94 * t_val + np.random.normal(0, 0.75)
        temp_ar[t] = t_val
    temperature = temp_seasonal + temp_ar
    
    # Demand (MW)
    temp_effect = 1.35 * np.maximum(0, 18.0 - temperature) + 2.15 * np.maximum(0, temperature - 22.0)
    diurnal_load = 28.0 * np.sin(2 * np.pi * (hod - 6) / 24) + 14.0 * np.sin(4 * np.pi * (hod - 6) / 24)
    demand = 410.0 + temp_effect * 3.8 + diurnal_load * 3.2 - 22.0 * is_weekend + np.random.normal(0, 7.5, size=n_hours)
    
    # Renewable Generation (Wind + Solar in MW)
    solar_cap_base = cfg["simulation_parameters"]["solar_capacity_mw_preshift"]
    solar_cap_shift = cfg["simulation_parameters"]["solar_capacity_mw_shifted"]
    solar_cap = np.where(np.arange(n_hours) >= 21900, solar_cap_shift, solar_cap_base)
    
    solar_profile = np.maximum(0.0, np.sin(np.pi * (hod - 6) / 13))
    solar_gen = solar_profile * np.random.uniform(0.65, 0.98, size=n_hours) * solar_cap
    
    wind_latent = np.zeros(n_hours)
    w_val = 65.0
    for t in range(n_hours):
        w_val = 0.97 * w_val + 0.03 * 72.0 + np.random.normal(0, 4.8)
        wind_latent[t] = max(10.0, w_val)
    renewable_gen = solar_gen + wind_latent
    
    net_load = demand - renewable_gen
    
    # Price formation ($/MWh)
    price = np.zeros(n_hours)
    p_prev = 48.0
    vol_state = 5.2
    
    for t in range(n_hours):
        is_shift = (t >= 21900)
        
        # Heat rate & marginal fuel cost
        hr = cfg["simulation_parameters"]["heat_rate_base"] + 0.0075 * (net_load[t] - 260.0)
        base_mc = hr * gas_price[t]
        
        # Merit-order convex ramp
        convex = 0.00038 * np.maximum(0, net_load[t] - 280.0)**2
        
        # Volatility process
        vol_target = 9.2 if is_shift else 5.2
        vol_state = 0.88 * vol_state + 0.12 * vol_target + np.random.normal(0, 1.1)
        vol_state = max(2.5, vol_state)
        
        # Autoregressive persistence
        ar = 0.60 * (p_prev - base_mc)
        mean_p = base_mc + convex + ar
        
        innov = np.random.normal(0, vol_state)
        
        # Jump process / price spikes
        spk_prob = 0.034 if is_shift else 0.015
        jump = 0.0
        if np.random.rand() < spk_prob:
            if net_load[t] > 320.0:
                jump = np.random.exponential(scale=68.0 if is_shift else 44.0) + 32.0
            elif renewable_gen[t] > 180.0 and demand[t] < 300.0:
                jump = -np.random.exponential(scale=24.0) - 12.0
            else:
                jump = np.random.exponential(scale=36.0) + 20.0
                
        p_t = mean_p + innov + jump
        p_t = np.clip(p_t, -25.0, 500.0)
        price[t] = p_t
        p_prev = p_t
        
    # Zones and delivery products
    # Zonal distribution:
    # In pre-shift: NP15 42%, SP15 45%, ZP26 13%
    # In shifted: ZP26 renewable volume expands to 25%, NP15 37%, SP15 38%
    z_probs_preshift = [0.42, 0.45, 0.13]
    z_probs_shift = [0.37, 0.38, 0.25]
    
    zone_assignment = np.empty(n_hours, dtype=object)
    zone_assignment[:21900] = np.random.choice(['NP15', 'SP15', 'ZP26'], size=21900, p=z_probs_preshift)
    zone_assignment[21900:] = np.random.choice(['NP15', 'SP15', 'ZP26'], size=n_hours - 21900, p=z_probs_shift)
    
    # Product types:
    # FIRM_DAY_AHEAD (standard commercial contract) ~ 86%
    # STANDBY_RESERVE (operational emergency override / non-firm dispatch) ~ 14%
    prod_type = np.random.choice(['FIRM_DAY_AHEAD', 'STANDBY_RESERVE'], size=n_hours, p=[0.86, 0.14])
    
    # Telemetry data quality:
    # NORMAL ~ 97%, ESTIMATED ~ 2%, MAINTENANCE ~ 1%
    telemetry = np.random.choice(['NORMAL', 'ESTIMATED', 'MAINTENANCE'], size=n_hours, p=[0.97, 0.02, 0.01])
    
    # In STANDBY_RESERVE, price is subject to emergency penalty settlements during grid distress:
    # Add non-firm penalty overrides to STANDBY_RESERVE during peak hours
    non_firm_idx = (prod_type == 'STANDBY_RESERVE')
    price[non_firm_idx] += np.random.choice([0.0, 45.0, 85.0], size=np.sum(non_firm_idx), p=[0.68, 0.22, 0.10])
    
    df = pd.DataFrame({
        'timestamp': timestamps,
        'zone': zone_assignment,
        'product_type': prod_type,
        'telemetry_status': telemetry,
        'demand_mw': np.round(demand, 2),
        'renewable_generation_mw': np.round(renewable_gen, 2),
        'temperature_c': np.round(temperature, 2),
        'fuel_index_usd_mmbtu': np.round(gas_price, 2),
        'hour': hod,
        'day_of_week': dow,
        'weekend_flag': is_weekend,
        'price_usd_mwh': np.round(price, 2)
    })
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    df.to_csv(output_path, index=False)
    print(f"Generated {len(df)} records saved to {output_path}")
    return df

if __name__ == "__main__":
    generate_power_market_dataset()
