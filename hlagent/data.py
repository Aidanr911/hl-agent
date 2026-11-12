"""Load HyperGrok research bundles (candles.csv + funding.csv)."""
from pathlib import Path

import numpy as np
import pandas as pd

H = 3_600_000
BAR = 4 * H


def load_candles(bundle: Path) -> pd.DataFrame:
    df = pd.read_csv(Path(bundle) / "candles.csv")
    df = df.set_index(pd.Index(df["t"].astype(np.int64), name="t"))[["o", "h", "l", "c", "v"]]
    return df.astype(float).sort_index()


def funding_per_bar(raw: pd.DataFrame, bar_index: pd.Index) -> pd.Series:
    """Sum hourly funding rates into the 4h bar during which they were paid.

    A print at hour h settles the position held over (h-1h, h], so it belongs to the
    bar whose span (t, t+4h] contains h. Prints carry millisecond jitter, so round first.
    """
    hour = (np.rint(raw["time"].to_numpy(dtype=float) / H) * H).astype(np.int64)
    bar = ((hour - 1) // BAR) * BAR
    s = pd.Series(raw["fundingRate"].to_numpy(dtype=float), index=bar).groupby(level=0).sum()
    return s.reindex(bar_index, fill_value=0.0).rename("funding")


def load_bundle(bundle: Path):
    candles = load_candles(bundle)
    raw = pd.read_csv(Path(bundle) / "funding.csv")
    return candles, funding_per_bar(raw, candles.index)
