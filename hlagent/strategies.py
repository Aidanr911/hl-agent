"""Signals in {-1, 0, +1}, computed at each bar close from data up to that close only."""
import numpy as np
import pandas as pd

BARS_PER_DAY = 6
DAY_MS = 86_400_000
BAR_MS = 4 * 3_600_000


def _state(enter_long, exit_long, enter_short, exit_short) -> np.ndarray:
    out = np.zeros(len(enter_long))
    pos = 0.0
    for i in range(len(out)):
        if pos > 0 and exit_long[i]:
            pos = 0.0
        elif pos < 0 and exit_short[i]:
            pos = 0.0
        if pos == 0.0:
            if enter_long[i]:
                pos = 1.0
            elif enter_short[i]:
                pos = -1.0
        out[i] = pos
    return out


def signal(name, candles: pd.DataFrame, funding: pd.Series, **p) -> pd.Series:
    c = candles["c"]
    if name in ("tsmom", "tsmom_long"):
        mom = c / c.shift(p["days"] * BARS_PER_DAY) - 1
        s = np.sign(mom).fillna(0.0)
        if name == "tsmom_long":
            s = s.clip(lower=0.0)
    elif name == "donchian":
        n, m = p["n"], max(2, p["n"] // 2)
        hi = candles["h"].rolling(n).max().shift(1)
        lo = candles["l"].rolling(n).min().shift(1)
        xhi = candles["h"].rolling(m).max().shift(1)
        xlo = candles["l"].rolling(m).min().shift(1)
        s = pd.Series(_state((c > hi).to_numpy(), (c < xlo).to_numpy(),
                             (c < lo).to_numpy(), (c > xhi).to_numpy()), index=c.index)
    elif name == "funding":
        ann = funding.rolling(p["days"] * BARS_PER_DAY).mean() * BARS_PER_DAY * 365
        s = pd.Series(np.where(ann > p["thresh"], -1.0, np.where(ann < -p["thresh"], 1.0, 0.0)), index=c.index)
    elif name == "meanrev":
        n, k = p["n"], p["k"]
        z = ((c - c.rolling(n).mean()) / c.rolling(n).std()).to_numpy()
        zn = np.nan_to_num(z)
        s = pd.Series(_state(zn < -k, zn >= 0, zn > k, zn <= 0), index=c.index)
    else:
        raise ValueError(name)
    return s.astype(float).rename(name)


def cross_sectional(candles: dict, days: int, top: int = 2) -> pd.DataFrame:
    """Long the `top` best and short the `top` worst trailing-return coins; re-ranked at 00:00 UTC closes."""
    closes = pd.DataFrame({s: df["c"] for s, df in candles.items()})
    mom = closes / closes.shift(days * BARS_PER_DAY) - 1
    rank = mom.rank(axis=1, method="first")
    n = closes.shape[1]
    w = pd.DataFrame(np.where(rank > n - top, 1.0, np.where(rank <= top, -1.0, 0.0)),
                     index=closes.index, columns=closes.columns)
    w[mom.isna().any(axis=1)] = np.nan
    daily = ((closes.index.to_numpy() + BAR_MS) % DAY_MS) == 0
    w[~daily] = np.nan
    return w.ffill().fillna(0.0)
