import numpy as np
import pandas as pd
from sklearn.metrics import precision_score, recall_score, f1_score
from evaluate import compute_wmape

def evaluate_spike_performance(y_true, y_pred, spike_threshold):
    """
    Spike forecasting metrics:
    - Interval-level binary threshold classification: y >= threshold
    - Conditional MAE and WMAPE on actual spikes
    """
    act_spk = (y_true >= spike_threshold).astype(int)
    pred_spk = (y_pred >= spike_threshold).astype(int)
    
    n_act = int(np.sum(act_spk))
    n_pred = int(np.sum(pred_spk))
    
    prec = float(precision_score(act_spk, pred_spk, zero_division=0))
    rec = float(recall_score(act_spk, pred_spk, zero_division=0))
    f1 = float(f1_score(act_spk, pred_spk, zero_division=0))
    
    # Conditional error
    if n_act > 0:
        spike_idx = (act_spk == 1)
        mae_spk = float(np.mean(np.abs(y_true[spike_idx] - y_pred[spike_idx])))
        wmape_spk = float(compute_wmape(y_true[spike_idx], y_pred[spike_idx]))
    else:
        mae_spk = 0.0
        wmape_spk = 0.0
        
    return {
        "spike_threshold": round(float(spike_threshold), 4),
        "actual_spikes": n_act,
        "predicted_spikes": n_pred,
        "spike_precision": round(prec, 4),
        "spike_recall": round(rec, 4),
        "spike_f1": round(f1, 4),
        "spike_mae": round(mae_spk, 4),
        "spike_wmape": round(wmape_spk, 4)
    }

def evaluate_macro_zone_spike(df, pred_col="predicted_price", target_col="price_usd_mwh", spike_threshold=82.0):
    """
    Macro-averaged spike recall across zones vs micro-averaged pooled recall.
    """
    zone_recalls = []
    zone_precisions = []
    for z in sorted(df['zone'].unique()):
        sub = df[df['zone'] == z]
        res = evaluate_spike_performance(sub[target_col].values, sub[pred_col].values, spike_threshold)
        zone_recalls.append(res['spike_recall'])
        zone_precisions.append(res['spike_precision'])
        
    return {
        "macro_spike_recall": round(float(np.mean(zone_recalls)), 4),
        "macro_spike_precision": round(float(np.mean(zone_precisions)), 4),
        "zonal_recalls": zone_recalls
    }
