from statistics import NormalDist

import numpy as np
import pandas as pd

PERIODS = 6 * 365  # 4h bars per year
N = NormalDist()


def sharpe(r: pd.Series, periods: int = PERIODS) -> float:
    r = pd.Series(r).dropna()
    sd = r.std(ddof=1)
    return 0.0 if not sd or np.isnan(sd) else float(r.mean() / sd * np.sqrt(periods))


def max_drawdown(equity: pd.Series) -> float:
    e = pd.Series(equity, dtype=float)
    return float((1 - e / e.cummax()).max())


def trade_stats(trade_pnls) -> dict:
    p = np.asarray(list(trade_pnls), dtype=float)
    wins, losses = p[p > 0].sum(), -p[p < 0].sum()
    return {
        "trades": int(len(p)),
        "win_rate": float((p > 0).mean()) if len(p) else float("nan"),
        "profit_factor": float(wins / losses) if losses > 0 else float("inf"),
    }


def trades_from(weights: pd.DataFrame, contrib: pd.DataFrame) -> list:
    """A trade = a run of same-signed non-zero held weight in one asset; PnL = its contributions.

    The bar after the run closes is included (that bar's return was earned by the run's last weight).
    """
    out = []
    for s in weights.columns:
        w = np.sign(weights[s].to_numpy())
        c = contrib[s].to_numpy()
        start = None
        for i in range(len(w) + 1):
            cur = w[i] if i < len(w) else 0.0
            prev = w[i - 1] if i > 0 else 0.0
            if start is not None and cur != prev:
                out.append(c[start:min(i + 1, len(c))].sum())
                start = None
            if cur != 0 and cur != prev:
                start = i
    return out


def deflated_sharpe(sr, n_obs, n_trials, sr_var, skew, kurt, periods=PERIODS) -> float:
    """Bailey & Lopez de Prado (2014). sr and sr_var are annualised; returns P(true SR > 0 | trials)."""
    srp, varp = sr / np.sqrt(periods), sr_var / periods
    if n_trials <= 1:
        sr0 = 0.0
    else:
        g = 0.5772156649
        sr0 = np.sqrt(varp) * ((1 - g) * N.inv_cdf(1 - 1 / n_trials) + g * N.inv_cdf(1 - 1 / (n_trials * np.e)))
    denom = np.sqrt(max(1e-12, 1 - skew * srp + (kurt - 1) / 4 * srp ** 2))
    return float(N.cdf((srp - sr0) * np.sqrt(n_obs - 1) / denom))
