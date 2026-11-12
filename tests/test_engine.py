import numpy as np
import pandas as pd
import pytest

from hlagent import data, engine, metrics, strategies

H = 3_600_000
BAR = 4 * H


def make_market(closes, funding_per_hour=0.0, start=0):
    n = len(closes)
    t = start + np.arange(n) * BAR
    c = np.asarray(closes, dtype=float)
    candles = pd.DataFrame({"o": c, "h": c, "l": c, "c": c, "v": 1.0}, index=pd.Index(t, name="t"))
    funding = pd.Series(funding_per_hour * 4, index=candles.index)
    return candles, funding


# ---------- data ----------

def test_funding_assigned_to_bar_it_was_paid_in():
    # bar 0 spans [0, 4h); prints at 1h..4h (with ms jitter) are paid while holding bar 0
    raw = pd.DataFrame({"time": [H + 114, 2 * H + 50, 3 * H + 7, 4 * H + 181, 5 * H + 3],
                        "fundingRate": [1.0, 1.0, 1.0, 1.0, 10.0]})
    out = data.funding_per_bar(raw, bar_index=pd.Index([0, BAR]))
    assert out.loc[0] == 4.0
    assert out.loc[BAR] == 10.0


# ---------- engine ----------

def test_constant_long_no_costs_equals_buy_and_hold():
    candles, funding = make_market([100, 110, 99, 120])
    w = pd.DataFrame({"X": 1.0}, index=candles.index)
    res = engine.run({"X": candles}, {"X": funding}, w, cost_bps={"X": 0.0}, band=0.0)
    assert res.equity.iloc[-1] == pytest.approx(1.20)


def test_weight_decided_at_close_earns_next_bar_only():
    candles, funding = make_market([100, 200, 100])
    # go long only at close of bar 1 -> earns bar 2 (-50%), not bar 1 (+100%)
    w = pd.DataFrame({"X": [0.0, 1.0, 1.0]}, index=candles.index)
    res = engine.run({"X": candles}, {"X": funding}, w, cost_bps={"X": 0.0}, band=0.0)
    assert res.equity.iloc[-1] == pytest.approx(0.5)


def test_costs_charged_on_turnover():
    candles, funding = make_market([100, 100, 100])
    w = pd.DataFrame({"X": [1.0, -1.0, -1.0]}, index=candles.index)
    res = engine.run({"X": candles}, {"X": funding}, w, cost_bps={"X": 10.0}, band=0.0)
    # turnover 1 at bar 0 open, 2 at flip: total 30 bps
    assert res.equity.iloc[-1] == pytest.approx((1 - 0.001) * (1 - 0.002))


def test_long_pays_positive_funding_short_receives():
    candles, funding = make_market([100, 100, 100], funding_per_hour=0.0001)
    for sign in (1.0, -1.0):
        w = pd.DataFrame({"X": sign}, index=candles.index)
        res = engine.run({"X": candles}, {"X": funding}, w, cost_bps={"X": 0.0}, band=0.0)
        expected = (1 - sign * 0.0004) ** 2
        assert res.equity.iloc[-1] == pytest.approx(expected)


def test_band_suppresses_small_rebalances_but_not_flips():
    tgt = np.array([1.0, 1.1, 0.95, -1.0, 0.0])
    held = engine.apply_band(tgt, band=0.2)
    assert list(held) == [1.0, 1.0, 1.0, -1.0, 0.0]


# ---------- no look-ahead in strategies ----------

@pytest.mark.parametrize("name,params", [
    ("tsmom", {"days": 5}), ("tsmom_long", {"days": 5}), ("donchian", {"n": 20}),
    ("funding", {"days": 1, "thresh": 0.2}), ("meanrev", {"n": 12, "k": 1.5}),
])
def test_signal_does_not_change_when_future_changes(name, params):
    rng = np.random.default_rng(0)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 400)))
    candles, funding = make_market(closes)
    funding[:] = rng.normal(0, 0.0002, 400)
    full = strategies.signal(name, candles, funding, **params)
    cut = 300
    altered = candles.copy()
    altered.iloc[cut:] *= 3.0
    f2 = funding.copy()
    f2.iloc[cut:] = 0.01
    part = strategies.signal(name, altered, f2, **params)
    pd.testing.assert_series_equal(full.iloc[:cut], part.iloc[:cut])


def test_cross_sectional_no_lookahead_and_dollar_neutral():
    rng = np.random.default_rng(1)
    mk = {}
    for i, s in enumerate("ABCDE"):
        mk[s] = make_market(100 * np.exp(np.cumsum(rng.normal(0, 0.02, 400))))[0]
    full = strategies.cross_sectional(mk, days=3)
    alt = {k: v.copy() for k, v in mk.items()}
    alt["A"].iloc[300:] *= 5
    part = strategies.cross_sectional(alt, days=3)
    pd.testing.assert_frame_equal(full.iloc[:300], part.iloc[:300])
    live = full.iloc[100:]
    assert np.allclose(live.sum(axis=1), 0.0)
    assert (live.abs().sum(axis=1) == 4).all()


# ---------- metrics ----------

def test_max_drawdown():
    eq = pd.Series([1.0, 1.2, 0.9, 1.3, 1.04])
    assert metrics.max_drawdown(eq) == pytest.approx(0.25)


def test_trade_stats_profit_factor_and_win_rate():
    pnl = [0.02, -0.01, 0.03, -0.02]
    s = metrics.trade_stats(pnl)
    assert s["trades"] == 4
    assert s["win_rate"] == pytest.approx(0.5)
    assert s["profit_factor"] == pytest.approx(0.05 / 0.03)


def test_deflated_sharpe_penalises_many_trials():
    one = metrics.deflated_sharpe(sr=1.5, n_obs=2000, n_trials=1, sr_var=0.1, skew=0, kurt=3, periods=2190)
    many = metrics.deflated_sharpe(sr=1.5, n_obs=2000, n_trials=50, sr_var=0.1, skew=0, kurt=3, periods=2190)
    assert 0 <= many < one <= 1
