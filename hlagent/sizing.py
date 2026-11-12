import numpy as np
import pandas as pd

PERIODS = 6 * 365


def vol_target(signal: pd.Series, candles: pd.DataFrame, target: float = 0.15, cap: float = 0.5,
               span: int = 180) -> pd.Series:
    """weight = signal * min(cap, target / sigma), sigma = EWMA realised vol known at the close."""
    r = np.log(candles["c"]).diff()
    sigma = np.sqrt((r ** 2).ewm(span=span, min_periods=span).mean() * PERIODS)
    w = signal * np.minimum(cap, target / sigma)
    return w.fillna(0.0)
