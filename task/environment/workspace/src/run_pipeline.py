import os
import yaml
import numpy as np
import pandas as pd
from features import build_feature_matrix, get_model_features
from models import get_model
from evaluate import compute_all_metrics, evaluate_by_zone, evaluate_by_regime, evaluate_by_zone_regime
from spike_metrics import evaluate_spike_performance, evaluate_macro_zone_spike
from bootstrap import block_bootstrap_wmape, iid_bootstrap_wmape

def run_pipeline():
    print("=== STARTING FULL EXPERIMENTAL PIPELINE ===")
    
    # 1. Load data & configuration
    with open("configs/data_config.yaml", "r") as f:
        data_cfg = yaml.safe_load(f)
        
    df_raw = pd.read_csv("data/market_clearing_observations.csv")
    n_total = len(df_raw)
    print(f"Loaded raw dataset with {n_total} records.")
    
    # 2. Build feature matrix
    df_feat = build_feature_matrix(df_raw, include_interaction=True)
    
    # 3. Splits
    # Train: 0 to 8759 (Year 1)
    # Validation: 8760 to 17519 (Year 2)
    # Test Pre-Shift: 17520 to 21899 (Year 3 H1)
    # Test Shifted: 21900 to 26279 (Year 3 H2)
    train_df = df_feat.iloc[:8760].copy()
    val_df = df_feat.iloc[8760:17520].copy()
    test_pre_df = df_feat.iloc[17520:21900].copy()
    test_shf_df = df_feat.iloc[21900:].copy()
    test_full_df = df_feat.iloc[17520:].copy()
    
    # 4. Regime Thresholds on TRAINING DATA ONLY (Strictly Causal)
    spike_thresh_frozen = float(np.percentile(train_df['price_usd_mwh'], 95))
    vol_thresh_frozen = float(np.percentile(train_df['roll_price_std_24'], 80))
    
    # Tempting Leaked Thresholds (calculated on post-shift test data)
    spike_thresh_leaked = float(np.percentile(test_shf_df['price_usd_mwh'], 95))
    vol_thresh_leaked = float(np.percentile(test_shf_df['roll_price_std_24'], 80))
    
    thresholds_record = [
        {
            "threshold_id": "FROZEN_PRE_SHIFT_P95",
            "provenance": "Fitted strictly on Year 1 Training partition (n=8,760)",
            "spike_price_threshold_usd": round(spike_thresh_frozen, 4),
            "volatile_rolling_std_threshold": round(vol_thresh_frozen, 4),
            "is_governing_standard": True
        },
        {
            "threshold_id": "LEAKED_POST_SHIFT_P95",
            "provenance": "Fitted ex-post on Year 3 H2 Shifted partition (n=4,380)",
            "spike_price_threshold_usd": round(spike_thresh_leaked, 4),
            "volatile_rolling_std_threshold": round(vol_thresh_leaked, 4),
            "is_governing_standard": False
        }
    ]
    pd.DataFrame(thresholds_record).to_csv("data/regime_thresholds.csv", index=False)
    print("Saved data/regime_thresholds.csv")
    
    # Tag regimes across all partitions using frozen threshold
    def assign_regime(df, s_th, v_th):
        reg = pd.Series("NORMAL", index=df.index)
        reg[df['roll_price_std_24'] >= v_th] = "VOLATILE"
        reg[df['price_usd_mwh'] >= s_th] = "SPIKE"
        return reg

    for d in [train_df, val_df, test_pre_df, test_shf_df, test_full_df]:
        d['regime'] = assign_regime(d, spike_thresh_frozen, vol_thresh_frozen)
        
    # Eligibility indicator for evaluation:
    for d in [train_df, val_df, test_pre_df, test_shf_df, test_full_df]:
        d['is_eligible_eval'] = (d['product_type'] == 'FIRM_DAY_AHEAD') & (d['telemetry_status'] == 'NORMAL')

    # Manifests
    split_manifest = [
        {"split": "TRAIN", "start_hour": 0, "end_hour": 8759, "count": 8760, "start_ts": str(train_df['timestamp'].iloc[0]), "end_ts": str(train_df['timestamp'].iloc[-1])},
        {"split": "VALIDATION", "start_hour": 8760, "end_hour": 17519, "count": 8760, "start_ts": str(val_df['timestamp'].iloc[0]), "end_ts": str(val_df['timestamp'].iloc[-1])},
        {"split": "TEST_PRE_SHIFT", "start_hour": 17520, "end_hour": 21899, "count": 4380, "start_ts": str(test_pre_df['timestamp'].iloc[0]), "end_ts": str(test_pre_df['timestamp'].iloc[-1])},
        {"split": "TEST_SHIFTED", "start_hour": 21900, "end_hour": 26279, "count": 4380, "start_ts": str(test_shf_df['timestamp'].iloc[0]), "end_ts": str(test_shf_df['timestamp'].iloc[-1])},
        {"split": "TEST_FULL", "start_hour": 17520, "end_hour": 26279, "count": 8760, "start_ts": str(test_full_df['timestamp'].iloc[0]), "end_ts": str(test_full_df['timestamp'].iloc[-1])}
    ]
    pd.DataFrame(split_manifest).to_csv("data/split_manifest.csv", index=False)
    print("Saved data/split_manifest.csv")
    
    # 5. Preliminary Run 001 (Archived vintage with base_no_interaction features)
    print("--- Executing Vintage Run 001 (Archived Preliminary Model) ---")
    df_feat_prelim = build_feature_matrix(df_raw, include_interaction=False)
    p_train = df_feat_prelim.iloc[:8760].copy()
    p_val = df_feat_prelim.iloc[8760:17520].copy()
    p_feats = get_model_features(p_train)
    
    prelim_rows = []
    models_to_run = [
        ("Persistence", "persistence_v0", {}),
        ("Ridge", "ridge_v0", {"alpha": 10.0}),
        ("RandomForest", "random_forest_v0", {"n_estimators": 80, "max_depth": 10}),
        ("HistGradientBoosting", "hist_gradient_boosting_v0", {"max_iter": 100, "max_depth": 6})
    ]
    for m_name, r_id, cfg in models_to_run:
        m = get_model(m_name, cfg)
        m.fit(p_train[p_feats], p_train['price_usd_mwh'])
        pred = m.predict(p_val[p_feats])
        met = compute_all_metrics(p_val['price_usd_mwh'].values, pred)
        met['model_name'] = m_name
        met['run_id'] = r_id
        met['vintage'] = "preliminary_v1"
        met['feature_set'] = "base_no_interaction"
        prelim_rows.append(met)
        
    df_prelim = pd.DataFrame(prelim_rows)[['model_name', 'run_id', 'vintage', 'feature_set', 'MAE', 'RMSE', 'WMAPE', 'R2', 'count']]
    os.makedirs("archive", exist_ok=True)
    df_prelim.to_csv("archive/preliminary_metrics.csv", index=False)
    print("Saved archive/preliminary_metrics.csv")
    
    # 6. Fit Final Model Vintage (Full Operational Feature Matrix)
    print("--- Fitting Final Production Candidate Models ---")
    feat_cols = get_model_features(train_df)
    
    fitted_models = {}
    model_cfgs = {
        "Persistence": ("persistence_v1", {}),
        "Ridge": ("ridge_reg_v1", {"alpha": 10.0}),
        "RandomForest": ("random_forest_v1", {"n_estimators": 80, "max_depth": 10}),
        "HistGradientBoosting": ("hist_gradient_boosting_v1", {"max_iter": 100, "max_depth": 6})
    }
    
    for m_name, (run_id, cfg) in model_cfgs.items():
        m = get_model(m_name, cfg)
        m.fit(train_df[feat_cols], train_df['price_usd_mwh'])
        fitted_models[m_name] = (m, run_id)
        
    # Generate and save predictions
    preds_val = {}
    preds_test_full = {}
    preds_test_shf = {}
    
    os.makedirs("predictions", exist_ok=True)
    for m_name, (m, run_id) in fitted_models.items():
        v_p = m.predict(val_df[feat_cols])
        t_p = m.predict(test_full_df[feat_cols])
        
        preds_val[m_name] = v_p
        preds_test_full[m_name] = t_p
        preds_test_shf[m_name] = t_p[4380:]
        
        # Save test prediction series
        out_pred = pd.DataFrame({
            "timestamp": test_full_df['timestamp'].values,
            "zone": test_full_df['zone'].values,
            "product_type": test_full_df['product_type'].values,
            "telemetry_status": test_full_df['telemetry_status'].values,
            "is_eligible_eval": test_full_df['is_eligible_eval'].values,
            "split_phase": np.where(np.arange(len(test_full_df)) < 4380, "PRE_SHIFT", "SHIFTED"),
            "actual_price": test_full_df['price_usd_mwh'].values,
            "predicted_price": np.round(t_p, 2)
        })
        fn = f"predictions/{m_name.lower()}_test.csv" if m_name != "HistGradientBoosting" else "predictions/hist_gradient_boosting_test.csv"
        out_pred.to_csv(fn, index=False)
        print(f"Saved {fn}")
        
    # 7. Model Selection Evaluation on VALIDATION Data (Year 2)
    print("--- Evaluating Model Selection Policy on Validation Period ---")
    val_records = []
    base_val_wmape = compute_all_metrics(val_df['price_usd_mwh'].values, preds_val["Persistence"])["WMAPE"]
    
    for m_name, (m, run_id) in fitted_models.items():
        vp = preds_val[m_name]
        ov = compute_all_metrics(val_df['price_usd_mwh'].values, vp)
        
        # Volatile regime
        val_eval_df = val_df.copy()
        val_eval_df['pred'] = vp
        sub_vol = val_eval_df[val_eval_df['regime'] == 'VOLATILE']
        vol_wmape = compute_all_metrics(sub_vol['price_usd_mwh'].values, sub_vol['pred'].values)['WMAPE']
        vol_deg_ratio = (vol_wmape - ov['WMAPE']) / ov['WMAPE'] if ov['WMAPE'] > 0 else 0.0
        
        # Spike recall
        spk_res = evaluate_spike_performance(val_df['price_usd_mwh'].values, vp, spike_thresh_frozen)
        
        # Relative improvement over persistence
        rel_imp = ((base_val_wmape - ov['WMAPE']) / base_val_wmape) * 100.0 if base_val_wmape > 0 else 0.0
        
        # Policy rules:
        # Rule 1: rel_imp >= 15.0%
        # Rule 2: spike recall >= 0.15
        # Rule 3: vol_deg_ratio <= 0.50
        r1 = bool(rel_imp >= 15.0)
        r2 = bool(spk_res['spike_recall'] >= 0.15)
        r3 = bool(vol_deg_ratio <= 0.50)
        is_elig = bool(r1 and r2 and r3)
        
        val_records.append({
            "model_name": m_name,
            "run_id": run_id,
            "validation_MAE": ov['MAE'],
            "validation_RMSE": ov['RMSE'],
            "validation_WMAPE": ov['WMAPE'],
            "validation_R2": ov['R2'],
            "rel_wmape_improvement_vs_persistence_pct": round(rel_imp, 2),
            "validation_spike_recall": spk_res['spike_recall'],
            "validation_spike_f1": spk_res['spike_f1'],
            "validation_volatile_wmape": vol_wmape,
            "volatile_degradation_ratio": round(vol_deg_ratio, 4),
            "rule1_improvement_passed": r1,
            "rule2_spike_recall_passed": r2,
            "rule3_volatility_stability_passed": r3,
            "is_eligible_for_selection": is_elig
        })
        
    os.makedirs("results", exist_ok=True)
    df_val_sel = pd.DataFrame(val_records)
    df_val_sel.to_csv("results/model_selection_validation.csv", index=False)
    print("Saved results/model_selection_validation.csv")
    
    # 8. Post-Selection Assessment: Overall & Shift Phase Metrics
    print("--- Computing Post-Selection Phase Metrics ---")
    # A. test_phase_metrics_eligible.csv (Governing population: product_type == FIRM_DAY_AHEAD & telemetry == NORMAL)
    phase_rows_elig = []
    # B. test_phase_metrics_pooled.csv (Trap 1: Pooled operational population including standby/overrides)
    phase_rows_pooled = []
    
    for m_name, (m, run_id) in fitted_models.items():
        pdf = pd.read_csv(f"predictions/{m_name.lower()}_test.csv" if m_name != "HistGradientBoosting" else "predictions/hist_gradient_boosting_test.csv")
        
        # Pooled
        p_pre = pdf[pdf['split_phase'] == 'PRE_SHIFT']
        p_shf = pdf[pdf['split_phase'] == 'SHIFTED']
        m_pre_p = compute_all_metrics(p_pre['actual_price'].values, p_pre['predicted_price'].values)
        m_pre_p.update({"model_name": m_name, "run_id": run_id, "phase": "PRE_SHIFT", "population": "POOLED_OPERATIONAL"})
        phase_rows_pooled.append(m_pre_p)
        m_shf_p = compute_all_metrics(p_shf['actual_price'].values, p_shf['predicted_price'].values)
        m_shf_p.update({"model_name": m_name, "run_id": run_id, "phase": "SHIFTED", "population": "POOLED_OPERATIONAL"})
        phase_rows_pooled.append(m_shf_p)
        
        # Eligible
        e_pre = pdf[(pdf['split_phase'] == 'PRE_SHIFT') & (pdf['is_eligible_eval'] == True)]
        e_shf = pdf[(pdf['split_phase'] == 'SHIFTED') & (pdf['is_eligible_eval'] == True)]
        m_pre_e = compute_all_metrics(e_pre['actual_price'].values, e_pre['predicted_price'].values)
        m_pre_e.update({"model_name": m_name, "run_id": run_id, "phase": "PRE_SHIFT", "population": "ELIGIBLE_COMMERCIAL"})
        phase_rows_elig.append(m_pre_e)
        m_shf_e = compute_all_metrics(e_shf['actual_price'].values, e_shf['predicted_price'].values)
        m_shf_e.update({"model_name": m_name, "run_id": run_id, "phase": "SHIFTED", "population": "ELIGIBLE_COMMERCIAL"})
        phase_rows_elig.append(m_shf_e)
        
    df_ph_elig = pd.DataFrame(phase_rows_elig)[['model_name', 'run_id', 'phase', 'population', 'MAE', 'RMSE', 'WMAPE', 'R2', 'count']]
    df_ph_elig.to_csv("results/test_phase_metrics_eligible.csv", index=False)
    
    df_ph_pooled = pd.DataFrame(phase_rows_pooled)[['model_name', 'run_id', 'phase', 'population', 'MAE', 'RMSE', 'WMAPE', 'R2', 'count']]
    df_ph_pooled.to_csv("results/test_phase_metrics_pooled.csv", index=False)
    print("Saved results/test_phase_metrics_eligible.csv and results/test_phase_metrics_pooled.csv")
    
    # 9. Shifted Subgroup Analysis (Zonal, Regime, Zonal-Regime)
    # Evaluated on Shifted Eligible Population
    shf_elig_eval = test_shf_df[test_shf_df['is_eligible_eval'] == True].copy()
    
    zonal_shf_rows = []
    reg_shf_rows = []
    zr_shf_rows = []
    
    for m_name, (m, run_id) in fitted_models.items():
        pdf = pd.read_csv(f"predictions/{m_name.lower()}_test.csv" if m_name != "HistGradientBoosting" else "predictions/hist_gradient_boosting_test.csv")
        p_shf_elig = pdf[(pdf['split_phase'] == 'SHIFTED') & (pdf['is_eligible_eval'] == True)].copy()
        
        # Merge regime from test_shf_df
        p_shf_elig['regime'] = shf_elig_eval['regime'].values
        p_shf_elig['price_usd_mwh'] = p_shf_elig['actual_price']
        
        # Zonal
        z_df = evaluate_by_zone(p_shf_elig, pred_col="predicted_price", target_col="actual_price")
        z_df['model_name'] = m_name
        z_df['run_id'] = run_id
        zonal_shf_rows.append(z_df)
        
        # Regime
        r_df = evaluate_by_regime(p_shf_elig, pred_col="predicted_price", target_col="actual_price")
        r_df['model_name'] = m_name
        r_df['run_id'] = run_id
        reg_shf_rows.append(r_df)
        
        # Zonal x Regime
        zr_df = evaluate_by_zone_regime(p_shf_elig, pred_col="predicted_price", target_col="actual_price")
        zr_df['model_name'] = m_name
        zr_df['run_id'] = run_id
        zr_shf_rows.append(zr_df)
        
    pd.concat(zonal_shf_rows)[['model_name', 'run_id', 'zone', 'MAE', 'RMSE', 'WMAPE', 'R2', 'count']].to_csv("results/shifted_zonal_metrics.csv", index=False)
    pd.concat(reg_shf_rows)[['model_name', 'run_id', 'regime', 'MAE', 'RMSE', 'WMAPE', 'R2', 'count']].to_csv("results/shifted_regime_metrics.csv", index=False)
    pd.concat(zr_shf_rows)[['model_name', 'run_id', 'zone', 'regime', 'MAE', 'RMSE', 'WMAPE', 'R2', 'count']].to_csv("results/shifted_zone_regime_metrics.csv", index=False)
    print("Saved shifted zonal, regime, and zone_regime CSVs.")
    
    # 10. Spike Performance on Shifted Interval (Frozen vs Leaked Thresholds; Eligible vs Pooled)
    spike_shf_rows = []
    for m_name, (m, run_id) in fitted_models.items():
        pdf = pd.read_csv(f"predictions/{m_name.lower()}_test.csv" if m_name != "HistGradientBoosting" else "predictions/hist_gradient_boosting_test.csv")
        
        # Eligible + Frozen Thresh (Governing standard)
        p_e = pdf[(pdf['split_phase'] == 'SHIFTED') & (pdf['is_eligible_eval'] == True)]
        spk_e_f = evaluate_spike_performance(p_e['actual_price'].values, p_e['predicted_price'].values, spike_thresh_frozen)
        spk_e_f.update({"model_name": m_name, "run_id": run_id, "population": "ELIGIBLE", "threshold_type": "FROZEN_PRE_SHIFT"})
        spike_shf_rows.append(spk_e_f)
        
        # Pooled + Frozen Thresh (Trap 1 population contamination)
        p_p = pdf[pdf['split_phase'] == 'SHIFTED']
        spk_p_f = evaluate_spike_performance(p_p['actual_price'].values, p_p['predicted_price'].values, spike_thresh_frozen)
        spk_p_f.update({"model_name": m_name, "run_id": run_id, "population": "POOLED", "threshold_type": "FROZEN_PRE_SHIFT"})
        spike_shf_rows.append(spk_p_f)
        
        # Eligible + Leaked Thresh (Trap 3 temporal leakage)
        spk_e_l = evaluate_spike_performance(p_e['actual_price'].values, p_e['predicted_price'].values, spike_thresh_leaked)
        spk_e_l.update({"model_name": m_name, "run_id": run_id, "population": "ELIGIBLE", "threshold_type": "LEAKED_POST_SHIFT"})
        spike_shf_rows.append(spk_e_l)
        
    df_spk_shf = pd.DataFrame(spike_shf_rows)[['model_name', 'run_id', 'population', 'threshold_type', 'spike_threshold', 'actual_spikes', 'predicted_spikes', 'spike_precision', 'spike_recall', 'spike_f1', 'spike_mae', 'spike_wmape']]
    df_spk_shf.to_csv("results/shifted_spike_metrics.csv", index=False)
    print("Saved results/shifted_spike_metrics.csv")
    
    # Macro vs Micro Spike Recall (Trap 4 Metric Semantics)
    macro_spike_rows = []
    for m_name, (m, run_id) in fitted_models.items():
        pdf = pd.read_csv(f"predictions/{m_name.lower()}_test.csv" if m_name != "HistGradientBoosting" else "predictions/hist_gradient_boosting_test.csv")
        p_e = pdf[(pdf['split_phase'] == 'SHIFTED') & (pdf['is_eligible_eval'] == True)]
        mac_res = evaluate_macro_zone_spike(p_e, pred_col="predicted_price", target_col="actual_price", spike_threshold=spike_thresh_frozen)
        mac_res.update({"model_name": m_name, "run_id": run_id})
        macro_spike_rows.append(mac_res)
    pd.DataFrame(macro_spike_rows).to_csv("results/shifted_macro_spike_metrics.csv", index=False)
    print("Saved results/shifted_macro_spike_metrics.csv")
    
    # 11. Statistical Uncertainty: Block Bootstrap vs Naive IID Resampling (Trap 6)
    print("--- Executing Statistical Uncertainty Bootstraps ---")
    p_ridge = pd.read_csv("predictions/ridge_test.csv")
    p_base = pd.read_csv("predictions/persistence_test.csv")
    
    shf_mask = (p_ridge['split_phase'] == 'SHIFTED') & (p_ridge['is_eligible_eval'] == True)
    y_true_boot = p_ridge[shf_mask]['actual_price'].values
    y_ridge_boot = p_ridge[shf_mask]['predicted_price'].values
    y_base_boot = p_base[shf_mask]['predicted_price'].values
    
    boot_block = block_bootstrap_wmape(y_true_boot, y_ridge_boot, y_base_boot, block_length=24, n_boot=400, seed=42)
    boot_block['candidate_model'] = "Ridge"
    boot_block['baseline_model'] = "Persistence"
    boot_block['population'] = "ELIGIBLE_SHIFTED"
    
    boot_iid = iid_bootstrap_wmape(y_true_boot, y_ridge_boot, y_base_boot, n_boot=400, seed=42)
    boot_iid['candidate_model'] = "Ridge"
    boot_iid['baseline_model'] = "Persistence"
    boot_iid['population'] = "ELIGIBLE_SHIFTED"
    
    df_boot = pd.DataFrame([boot_block, boot_iid])
    df_boot.to_csv("results/bootstrap_uncertainty_comparison.csv", index=False)
    print("Saved results/bootstrap_uncertainty_comparison.csv")
    
    print("=== PIPELINE EXECUTION COMPLETED SUCCESSFULLY ===")

if __name__ == "__main__":
    run_pipeline()
