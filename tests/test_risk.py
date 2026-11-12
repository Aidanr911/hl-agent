import pytest

from hlagent.risk import Limits, RiskEngine, RiskState

L = Limits(max_pos=0.5, max_gross=1.0, daily_loss=0.03, max_drawdown=0.15,
           stale_after_s=3600, max_api_errors=3)


def check(targets, current=None, equity=10_000, state=None, ages=None, api_errors=0, kill_file=False):
    state = state or RiskState(day="2026-11-12", day_start_equity=10_000, peak_equity=10_000)
    current = current or {k: 0.0 for k in targets}
    ages = ages or {k: 10 for k in targets}
    return RiskEngine(L).check(targets, current, equity, state, ages, api_errors, kill_file)


def test_clips_each_position_to_max():
    d = check({"BTC": 0.9, "ETH": -0.7})
    assert d.targets == {"BTC": 0.5, "ETH": -0.5}
    assert any("clip" in r for r in d.notes)


def test_scales_gross_down_proportionally():
    d = check({"BTC": 0.5, "ETH": 0.5, "SOL": -0.5})
    assert sum(abs(v) for v in d.targets.values()) == pytest.approx(1.0)
    assert d.targets["BTC"] == pytest.approx(1 / 3)


def test_daily_loss_flattens_and_latches_for_the_day():
    st = RiskState(day="2026-11-12", day_start_equity=10_000, peak_equity=10_000)
    d = check({"BTC": 0.3}, current={"BTC": 0.3}, equity=9_690, state=st)
    assert d.targets == {"BTC": 0.0}
    assert st.halted_until_day == "2026-11-13"
    # equity recovers the same day: still halted
    d2 = check({"BTC": 0.3}, equity=10_000, state=st)
    assert d2.targets == {"BTC": 0.0}


def test_drawdown_kill_is_latched_until_manual_reset():
    st = RiskState(day="2026-11-12", day_start_equity=8_600, peak_equity=10_000)
    d = check({"BTC": 0.3}, current={"BTC": 0.3}, equity=8_400, state=st)
    assert d.targets == {"BTC": 0.0} and st.killed
    st.day, st.day_start_equity = "2026-12-01", 9_000
    assert check({"BTC": 0.3}, equity=9_000, state=st).targets == {"BTC": 0.0}
    st.reset_kill()
    assert check({"BTC": 0.3}, equity=9_000, state=st).targets == {"BTC": 0.3}


def test_kill_file_flattens_everything_and_latches():
    st = RiskState(day="2026-11-12", day_start_equity=10_000, peak_equity=10_000)
    d = check({"BTC": 0.3, "ETH": -0.2}, current={"BTC": 0.3, "ETH": -0.2}, state=st, kill_file=True)
    assert d.targets == {"BTC": 0.0, "ETH": 0.0} and st.killed


def test_stale_coin_is_frozen_not_traded():
    d = check({"BTC": 0.3, "ETH": 0.3}, current={"BTC": 0.1, "ETH": 0.0}, ages={"BTC": 99_999, "ETH": 5})
    assert d.targets == {"BTC": 0.1, "ETH": 0.3}
    assert any("stale" in r for r in d.notes)


def test_api_error_storm_freezes_all_trading():
    d = check({"BTC": 0.3}, current={"BTC": 0.1}, api_errors=3)
    assert d.targets == {"BTC": 0.1}
    assert any("api" in r for r in d.notes)


def test_loss_limits_beat_frozen_data():
    # even with stale data, a kill must flatten
    d = check({"BTC": 0.3}, current={"BTC": 0.3}, ages={"BTC": 99_999}, kill_file=True)
    assert d.targets == {"BTC": 0.0}
