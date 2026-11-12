import json

import numpy as np
import pandas as pd
import pytest

from hlagent.live.agent import Agent, Config
from hlagent.live.paper import PaperBroker

BAR = 4 * 3_600_000


# ---------- paper broker ----------

def test_fill_charges_fee_and_slippage_and_rounds_size():
    b = PaperBroker(equity=10_000, fee_bps=4.5, slip_bps={"BTC": 2.0}, sz_decimals={"BTC": 3})
    fill = b.rebalance("BTC", target_size=0.12345, mid=50_000)
    assert fill["size"] == pytest.approx(0.123)
    notional = 0.123 * 50_000
    assert b.equity == pytest.approx(10_000 - notional * 6.5e-4)
    assert b.positions["BTC"] == pytest.approx(0.123)


def test_mark_to_market_and_short_pnl():
    b = PaperBroker(equity=10_000, fee_bps=0, slip_bps={"ETH": 0}, sz_decimals={"ETH": 2})
    b.rebalance("ETH", target_size=-2.0, mid=2_000)
    b.mark({"ETH": 1_900})
    assert b.equity == pytest.approx(10_200)


def test_funding_long_pays_positive_rate_once_per_print():
    b = PaperBroker(equity=10_000, fee_bps=0, slip_bps={"BTC": 0}, sz_decimals={"BTC": 3})
    b.rebalance("BTC", target_size=0.1, mid=50_000)
    prints = [(1000, 0.0001), (2000, 0.0001)]
    b.accrue_funding("BTC", prints, mid=50_000)
    b.accrue_funding("BTC", prints, mid=50_000)   # same prints again: no double charge
    assert b.equity == pytest.approx(10_000 - 2 * 0.1 * 50_000 * 0.0001)


def test_orders_below_min_notional_are_skipped():
    b = PaperBroker(equity=10_000, fee_bps=4.5, slip_bps={"BTC": 2}, sz_decimals={"BTC": 5})
    assert b.rebalance("BTC", target_size=0.0001, mid=50_000) is None   # $5
    assert b.positions.get("BTC", 0.0) == 0.0


def test_state_round_trips(tmp_path):
    b = PaperBroker(equity=10_000, fee_bps=4.5, slip_bps={"BTC": 2}, sz_decimals={"BTC": 3})
    b.rebalance("BTC", target_size=0.1, mid=50_000)
    p = tmp_path / "s.json"
    p.write_text(json.dumps(b.to_dict()))
    b2 = PaperBroker.from_dict(json.loads(p.read_text()))
    assert b2.to_dict() == b.to_dict()


# ---------- agent with a fake feed ----------

class FakeFeed:
    def __init__(self, n_bars=800, now_bar=800, price=100.0, drift=0.002):
        self.n, self.now_bar, self.price, self.drift = n_bars, now_bar, price, drift
        self.errors = 0

    def now_ms(self):
        return self.now_bar * BAR + 60_000

    def meta(self):
        return {"X": 2}

    def mids(self):
        return {"X": self.price * np.exp(self.drift * (self.now_bar - 1))}

    def candles(self, coin, n):
        t = np.arange(self.now_bar - n, self.now_bar) * BAR
        c = self.price * np.exp(self.drift * np.arange(self.now_bar - n, self.now_bar))
        c = c * (1 + 0.01 * np.sin(np.arange(len(c))))   # some volatility
        return pd.DataFrame({"o": c, "h": c, "l": c, "c": c, "v": 1.0}, index=pd.Index(t, name="t"))

    def funding(self, coin, since_ms):
        return []


def make_agent(tmp_path, feed, **kw):
    cfg = Config(coins=["X"], state_dir=str(tmp_path), strategy={"name": "tsmom", "days": 5},
                 strategy_status="REJECTED", start_equity=10_000, slip_bps={"X": 2.0}, **kw)
    return Agent(cfg, feed)


def test_agent_trades_on_new_bar_only_and_journals(tmp_path):
    feed = FakeFeed()
    a = make_agent(tmp_path, feed)
    r1 = a.tick()
    assert r1["decided"] and r1["broker"]["positions"]["X"] > 0   # uptrend -> long
    r2 = a.tick()
    assert not r2["decided"]                                       # same bar: no new decision
    lines = (tmp_path / "journal.jsonl").read_text().splitlines()
    assert len(lines) == 2
    rec = json.loads(lines[0])
    assert {"inputs", "signals", "risk", "orders", "result"} <= set(rec)
    assert rec["mode"] == "shadow" and rec["strategy_status"] == "REJECTED"


def test_kill_file_flattens_paper_book(tmp_path):
    feed = FakeFeed()
    a = make_agent(tmp_path, feed)
    a.tick()
    (tmp_path / "KILL").write_text("stop")
    feed.now_bar += 1
    r = a.tick()
    assert r["broker"]["positions"].get("X", 0.0) == 0.0
    assert r["risk_state"]["killed"]


def test_state_persists_across_restarts(tmp_path):
    feed = FakeFeed()
    make_agent(tmp_path, feed).tick()
    a2 = make_agent(tmp_path, feed)
    assert a2.broker.positions["X"] > 0
    assert not a2.tick()["decided"]


def test_agent_has_no_live_order_path():
    import hlagent.live.agent as mod
    src = open(mod.__file__).read()
    for word in ("/exchange", "sign_l1_action", "private_key", "eth_account"):
        assert word not in src
