"""Bar-close backtest engine. Weights decided at the close of bar t earn bar t+1.

Per bar, for each asset:  pnl[t+1] = w[t] * (c[t+1]/c[t] - 1) - w[t] * funding[t+1]
Rebalance cost at the close of bar t: |w[t] - w[t-1]| * cost_bps / 1e4.
Weights are fractions of equity, re-struck every bar (no intrabar fills, no drift).
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd


def apply_band(target, band: float) -> np.ndarray:
    """Hold the previous weight unless the target flips sign, goes flat, or moves > band*|target|."""
    target = np.nan_to_num(np.asarray(target, dtype=float))
    held = np.zeros_like(target)
    cur = 0.0
    for i, x in enumerate(target):
        if x == 0.0 or cur == 0.0 or np.sign(x) != np.sign(cur) or abs(x - cur) > band * abs(x):
            cur = x
        held[i] = cur
    return held


@dataclass
class Result:
    equity: pd.Series          # equity after each bar close (start = 1.0)
    returns: pd.Series         # per-bar portfolio return, net
    contrib: pd.DataFrame      # per-asset per-bar net contribution
    weights: pd.DataFrame      # held weights
    turnover: pd.Series


def run(candles: dict, funding: dict, target: pd.DataFrame, cost_bps: dict, band: float = 0.2) -> Result:
    idx = target.index
    syms = list(target.columns)
    held = pd.DataFrame({s: apply_band(target[s].to_numpy(), band) for s in syms}, index=idx)
    contrib = pd.DataFrame(0.0, index=idx, columns=syms)
    turnover = pd.Series(0.0, index=idx)
    for s in syms:
        c = candles[s]["c"].reindex(idx).to_numpy()
        f = funding[s].reindex(idx, fill_value=0.0).to_numpy()
        w = held[s].to_numpy()
        w_prev = np.concatenate([[0.0], w[:-1]])
        ret = np.concatenate([[0.0], c[1:] / c[:-1] - 1.0])
        fund = np.concatenate([[0.0], f[1:]])
        trade = np.abs(w - w_prev)
        contrib[s] = w_prev * ret - w_prev * fund - trade * cost_bps[s] / 1e4
        turnover += trade
    r = contrib.sum(axis=1)
    equity = (1.0 + r).cumprod()
    return Result(equity, r, contrib, held, turnover)
