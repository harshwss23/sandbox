import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

def compute_wmape(y_true, y_pred):
    """
    Weighted Mean Absolute Percentage Error (WMAPE):
    WMAPE = sum(|y_true - y_pred|) / sum(|y_true|)
    """
    sum_err = np.sum(np.abs(y_true - y_pred))
    sum_true = np.sum(np.abs(y_true))
    return float(sum_err / sum_true) if sum_true > 0 else 0.0

def compute_all_metrics(y_true, y_pred):
    mae = float(mean_absolute_error(y_true, y_pred))
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    wmape = float(compute_wmape(y_true, y_pred))
    r2 = float(r2_score(y_true, y_pred))
    return {
        "MAE": round(mae, 4),
        "RMSE": round(rmse, 4),
        "WMAPE": round(wmape, 4),
        "R2": round(r2, 4),
        "count": int(len(y_true))
    }

def evaluate_by_zone(df, pred_col="predicted_price", target_col="price_usd_mwh"):
    rows = []
    for z in sorted(df['zone'].unique()):
        sub = df[df['zone'] == z]
        m = compute_all_metrics(sub[target_col].values, sub[pred_col].values)
        m['zone'] = z
        rows.append(m)
    return pd.DataFrame(rows)

def evaluate_by_regime(df, pred_col="predicted_price", target_col="price_usd_mwh"):
    rows = []
    for reg in ['NORMAL', 'VOLATILE', 'SPIKE']:
        sub = df[df['regime'] == reg]
        if len(sub) > 0:
            m = compute_all_metrics(sub[target_col].values, sub[pred_col].values)
            m['regime'] = reg
            rows.append(m)
    return pd.DataFrame(rows)

def evaluate_by_zone_regime(df, pred_col="predicted_price", target_col="price_usd_mwh"):
    rows = []
    for z in sorted(df['zone'].unique()):
        for reg in ['NORMAL', 'VOLATILE', 'SPIKE']:
            sub = df[(df['zone'] == z) & (df['regime'] == reg)]
            if len(sub) > 0:
                m = compute_all_metrics(sub[target_col].values, sub[pred_col].values)
                m['zone'] = z
                m['regime'] = reg
                rows.append(m)
    return pd.DataFrame(rows)
