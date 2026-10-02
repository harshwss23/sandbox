import numpy as np
import pandas as pd

def build_feature_matrix(df, include_interaction=True):
    """
    Construct strictly causal, non-leaking features for 1-hour-ahead electricity price forecasting.
    Features available at time t before price_t is realized:
    - Exogenous forecasts: demand_mw, renewable_generation_mw, temperature_c, fuel_index_usd_mmbtu
    - Calendar: hour, day_of_week, weekend_flag, cyclical harmonics
    - Lags: lag_1, lag_24, lag_168
    - Rolling statistics: rolling mean and std over past 24 hours (strictly shifted by 1)
    - Net load: demand - renewable_generation
    """
    df = df.copy()
    
    # Endogenous price lags
    df['lag_price_1'] = df['price_usd_mwh'].shift(1).bfill()
    df['lag_price_2'] = df['price_usd_mwh'].shift(2).bfill()
    df['lag_price_24'] = df['price_usd_mwh'].shift(24).bfill()
    df['lag_price_168'] = df['price_usd_mwh'].shift(168).bfill()
    
    # Strictly causal rolling features (shifted from t-1 backward)
    shifted_p = df['price_usd_mwh'].shift(1)
    df['roll_price_mean_24'] = shifted_p.rolling(24, min_periods=1).mean().bfill()
    df['roll_price_std_24'] = shifted_p.rolling(24, min_periods=1).std().fillna(0.0)
    
    # Net load
    df['net_load_mw'] = df['demand_mw'] - df['renewable_generation_mw']
    
    # Harmonics
    df['hour_sin'] = np.sin(2 * np.pi * df['hour'] / 24.0)
    df['hour_cos'] = np.cos(2 * np.pi * df['hour'] / 24.0)
    df['dow_sin'] = np.sin(2 * np.pi * df['day_of_week'] / 7.0)
    df['dow_cos'] = np.cos(2 * np.pi * df['day_of_week'] / 7.0)
    
    if include_interaction:
        # Non-linear thermal efficiency and merit order interaction
        df['net_load_squared'] = (df['net_load_mw'] / 100.0) ** 2
        df['fuel_heat_interaction'] = (df['fuel_index_usd_mmbtu'] * df['net_load_mw']) / 100.0
        df['temp_heating_deg'] = np.maximum(0.0, 18.0 - df['temperature_c'])
        df['temp_cooling_deg'] = np.maximum(0.0, df['temperature_c'] - 22.0)
        
    # Zonal dummy variables
    zone_dummies = pd.get_dummies(df['zone'], prefix='zone', dtype=float)
    df = pd.concat([df, zone_dummies], axis=1)
    
    return df

def get_model_features(df):
    excluded = [
        'timestamp', 'zone', 'product_type', 'telemetry_status',
        'price_usd_mwh', 'regime', 'split_phase', 'is_eligible_eval'
    ]
    return [c for c in df.columns if c not in excluded]
