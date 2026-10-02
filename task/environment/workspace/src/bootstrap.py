import numpy as np
import pandas as pd
from evaluate import compute_wmape

def block_bootstrap_wmape(y_true, y_pred_cand, y_pred_base, block_length=24, n_boot=400, seed=42):
    """
    Moving Block Bootstrap (MBB) for time-series dependent observation resampling.
    """
    np.random.seed(seed)
    n = len(y_true)
    n_blocks = int(np.ceil(n / block_length))
    possible_starts = n - block_length + 1
    
    diff_boot = np.zeros(n_boot)
    rel_boot = np.zeros(n_boot)
    
    w_base_pt = compute_wmape(y_true, y_pred_base)
    w_cand_pt = compute_wmape(y_true, y_pred_cand)
    abs_diff_pt = w_base_pt - w_cand_pt
    rel_imp_pt = (abs_diff_pt / w_base_pt) * 100.0 if w_base_pt > 0 else 0.0
    
    for b in range(n_boot):
        starts = np.random.randint(0, possible_starts, size=n_blocks)
        indices = np.concatenate([np.arange(s, s + block_length) for s in starts])[:n]
        
        wb = compute_wmape(y_true[indices], y_pred_base[indices])
        wc = compute_wmape(y_true[indices], y_pred_cand[indices])
        diff_boot[b] = wb - wc
        rel_boot[b] = ((wb - wc) / wb) * 100.0 if wb > 0 else 0.0
        
    return {
        "candidate_wmape": round(w_cand_pt, 4),
        "baseline_wmape": round(w_base_pt, 4),
        "abs_diff_point": round(abs_diff_pt, 4),
        "rel_imp_point_pct": round(rel_imp_pt, 2),
        "ci_abs_lower_95": round(float(np.percentile(diff_boot, 2.5)), 4),
        "ci_abs_upper_95": round(float(np.percentile(diff_boot, 97.5)), 4),
        "ci_rel_lower_95_pct": round(float(np.percentile(rel_boot, 2.5)), 2),
        "ci_rel_upper_95_pct": round(float(np.percentile(rel_boot, 97.5)), 2),
        "method": "moving_block_bootstrap",
        "block_length": block_length,
        "n_replicates": n_boot
    }

def iid_bootstrap_wmape(y_true, y_pred_cand, y_pred_base, n_boot=400, seed=42):
    """
    Naive Independent and Identically Distributed (IID) Resampling.
    Assumes temporal observations are independent (incorrect for hourly electricity loads/prices).
    """
    np.random.seed(seed)
    n = len(y_true)
    diff_boot = np.zeros(n_boot)
    rel_boot = np.zeros(n_boot)
    
    w_base_pt = compute_wmape(y_true, y_pred_base)
    w_cand_pt = compute_wmape(y_true, y_pred_cand)
    abs_diff_pt = w_base_pt - w_cand_pt
    rel_imp_pt = (abs_diff_pt / w_base_pt) * 100.0 if w_base_pt > 0 else 0.0
    
    for b in range(n_boot):
        indices = np.random.randint(0, n, size=n)
        wb = compute_wmape(y_true[indices], y_pred_base[indices])
        wc = compute_wmape(y_true[indices], y_pred_cand[indices])
        diff_boot[b] = wb - wc
        rel_boot[b] = ((wb - wc) / wb) * 100.0 if wb > 0 else 0.0
        
    return {
        "candidate_wmape": round(w_cand_pt, 4),
        "baseline_wmape": round(w_base_pt, 4),
        "abs_diff_point": round(abs_diff_pt, 4),
        "rel_imp_point_pct": round(rel_imp_pt, 2),
        "ci_abs_lower_95": round(float(np.percentile(diff_boot, 2.5)), 4),
        "ci_abs_upper_95": round(float(np.percentile(diff_boot, 97.5)), 4),
        "ci_rel_lower_95_pct": round(float(np.percentile(rel_boot, 2.5)), 2),
        "ci_rel_upper_95_pct": round(float(np.percentile(rel_boot, 97.5)), 2),
        "method": "naive_iid_resampling",
        "block_length": 1,
        "n_replicates": n_boot
    }
