import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline

class PersistenceForecaster:
    """
    Persistence Baseline Forecaster:
    Forecasts price at time t as the most recently observed price (lag_price_1).
    """
    def __init__(self):
        self.model_name = "Persistence"
        self.lag_col = "lag_price_1"
        
    def fit(self, X, y=None):
        return self
        
    def predict(self, X):
        return np.array(X[self.lag_col])

def get_model(model_type, config=None):
    if config is None:
        config = {}
        
    m_type = model_type.lower()
    if m_type == "persistence":
        return PersistenceForecaster()
        
    elif m_type == "ridge":
        alpha = config.get("alpha", 10.0)
        fit_intercept = config.get("fit_intercept", True)
        random_state = config.get("random_state", 42)
        pipe = Pipeline([
            ("scaler", StandardScaler()),
            ("regressor", Ridge(alpha=alpha, fit_intercept=fit_intercept, random_state=random_state))
        ])
        return pipe
        
    elif m_type in ["randomforest", "random_forest"]:
        n_estimators = config.get("n_estimators", 80)
        max_depth = config.get("max_depth", 10)
        min_samples_split = config.get("min_samples_split", 10)
        min_samples_leaf = config.get("min_samples_leaf", 5)
        n_jobs = config.get("n_jobs", -1)
        random_state = config.get("random_state", 42)
        return RandomForestRegressor(
            n_estimators=n_estimators,
            max_depth=max_depth,
            min_samples_split=min_samples_split,
            min_samples_leaf=min_samples_leaf,
            n_jobs=n_jobs,
            random_state=random_state
        )
        
    elif m_type in ["histgradientboosting", "hist_gradient_boosting"]:
        learning_rate = config.get("learning_rate", 0.08)
        max_iter = config.get("max_iter", 100)
        max_depth = config.get("max_depth", 6)
        min_samples_leaf = config.get("min_samples_leaf", 20)
        l2_reg = config.get("l2_regularization", 1.0)
        random_state = config.get("random_state", 42)
        return HistGradientBoostingRegressor(
            learning_rate=learning_rate,
            max_iter=max_iter,
            max_depth=max_depth,
            min_samples_leaf=min_samples_leaf,
            l2_regularization=l2_reg,
            random_state=random_state,
            early_stopping=False
        )
    else:
        raise ValueError(f"Unknown model_type: {model_type}")
