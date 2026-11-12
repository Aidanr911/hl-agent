"""Disarmed 24/7 agent: live read-only data -> signal -> sizing -> hard risk limits -> PLAY-MONEY broker.

There is deliberately no code path here that signs or sends an order to any exchange.
Usage:
  python3 -m hlagent.live.agent tick        # one cycle
  python3 -m hlagent.live.agent loop        # run forever (polls every 5 min, decides on 4h closes)
  python3 -m hlagent.live.agent status
  python3 -m hlagent.live.agent kill        # flatten paper book and latch
  python3 -m hlagent.live.agent reset-kill
"""
import argparse
import json
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from hlagent import sizing, strategies
from hlagent.live.paper import PaperBroker
from hlagent.risk import Limits, RiskEngine, RiskState

BAR = 4 * 3_600_000


@dataclass
class Config:
    coins: list = field(default_factory=lambda: ["BTC", "ETH", "SOL", "XRP", "DOGE"])
    state_dir: str = "state"
    strategy: dict = field(default_factory=lambda: {"name": "tsmom", "days": 90})
    strategy_status: str = "REJECTED"          # from docs/REPORT.md
    mode: str = "shadow"                        # shadow = play money only; there is no other mode
    start_equity: float = 10_000.0
    fee_bps: float = 4.5
    slip_bps: dict = field(default_factory=lambda: {"BTC": 2.0, "ETH": 2.0, "SOL": 4.0, "XRP": 4.0, "DOGE": 4.0})
    vol_target: float = 0.15
    max_weight: float = 0.5
    band: float = 0.2
    poll_s: int = 300
    limits: Limits = field(default_factory=Limits)


def _utc(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


class Agent:
    def __init__(self, cfg: Config, feed):
        assert cfg.mode == "shadow", "only play-money shadow mode exists"
        self.cfg, self.feed = cfg, feed
        self.dir = Path(cfg.state_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.risk = RiskEngine(cfg.limits)
        p = self.dir / "state.json"
        if p.exists():
            s = json.loads(p.read_text())
            self.broker = PaperBroker.from_dict(s["broker"])
            self.rs = RiskState(**s["risk_state"])
            self.last_bar = s["last_decision_bar"]
        else:
            now = feed.now_ms()
            szd = feed.meta()
            self.broker = PaperBroker(cfg.start_equity, cfg.fee_bps, cfg.slip_bps,
                                      {c: szd.get(c, 4) for c in cfg.coins},
                                      last_funding_ms={c: now for c in cfg.coins})
            self.rs = RiskState(day=_utc(now).date().isoformat(),
                                day_start_equity=cfg.start_equity, peak_equity=cfg.start_equity)
            self.last_bar = -1

    def _lookback(self):
        st = self.cfg.strategy
        need = st.get("days", 0) * 6 + 1 if "days" in st else st.get("n", 0) + 1
        return max(need, 181) + 20

    def _signal(self, coin):
        st = dict(self.cfg.strategy)
        name = st.pop("name")
        c = self.feed.candles(coin, self._lookback())
        f = c["c"] * 0.0   # live funding history not needed for price-based strategies
        sig = strategies.signal(name, c, f, **st)
        w = sizing.vol_target(sig, c, target=self.cfg.vol_target, cap=self.cfg.max_weight)
        age_s = (self.feed.now_ms() - (int(c.index[-1]) + BAR)) / 1000
        return float(sig.iloc[-1]), float(w.iloc[-1]), age_s, int(c.index[-1])

    def _should_trade(self, cur, tgt):
        if tgt == 0.0 or cur == 0.0 or (tgt > 0) != (cur > 0):
            return tgt != cur
        return abs(tgt - cur) > self.cfg.band * abs(tgt)

    def tick(self):
        cfg, b = self.cfg, self.broker
        now = self.feed.now_ms()
        errors, notes = 0, []
        try:
            mids = {c: v for c, v in self.feed.mids().items() if c in cfg.coins}
        except Exception as e:  # noqa: BLE001
            errors, mids = errors + 1, {}
            notes.append(f"mids error: {e}")
        b.mark(mids)
        for c in cfg.coins:
            if c in mids and b.positions.get(c):
                try:
                    b.accrue_funding(c, self.feed.funding(c, b.last_funding_ms.get(c, now)), mids[c])
                except Exception as e:  # noqa: BLE001
                    errors += 1
                    notes.append(f"{c} funding error: {e}")
            elif c in mids:
                b.last_funding_ms[c] = now

        day = _utc(now).date().isoformat()
        if day != self.rs.day:
            self.rs.day, self.rs.day_start_equity = day, b.equity
        self.rs.peak_equity = max(self.rs.peak_equity, b.equity)

        last_closed = (now // BAR - 1) * BAR
        decided = last_closed > self.last_bar
        current = {c: b.weights().get(c, 0.0) for c in cfg.coins}
        raw, targets, ages = {}, dict(current), {c: (0 if c in mids else float("inf")) for c in cfg.coins}
        if decided:
            for c in cfg.coins:
                try:
                    raw[c], targets[c], ages[c], _ = self._signal(c)
                except Exception as e:  # noqa: BLE001
                    errors += 1
                    ages[c] = float("inf")
                    notes.append(f"{c} candles error: {e}")

        d = self.risk.check(targets, current, b.equity, self.rs, ages, errors, (self.dir / "KILL").exists())
        orders = []
        if decided or d.flattened:
            for c in cfg.coins:
                tgt = d.targets[c]
                if c in mids and self._should_trade(current[c], tgt):
                    fill = b.rebalance(c, tgt * b.equity / mids[c], mids[c])
                    if fill:
                        orders.append(fill)
        if decided and errors < cfg.limits.max_api_errors:
            self.last_bar = last_closed

        rec = {
            "ts": _utc(now).isoformat(), "mode": cfg.mode, "strategy": cfg.strategy,
            "strategy_status": cfg.strategy_status, "decided": decided,
            "bar_closed": _utc(last_closed + BAR).isoformat(),
            "inputs": {"mids": mids, "data_age_s": ages, "weights_before": current, "errors": errors, "notes": notes},
            "signals": {"raw": raw, "sized": {c: targets[c] for c in raw}},
            "risk": {"targets": d.targets, "notes": d.notes, "flattened": d.flattened},
            "orders": orders,
            "result": {"equity": b.equity, "positions": b.positions, "weights_after": b.weights()},
        }
        with open(self.dir / "journal.jsonl", "a") as fh:
            fh.write(json.dumps(rec, default=float) + "\n")
        self.save()
        return {"decided": decided, "broker": b.to_dict(), "risk_state": asdict(self.rs), "record": rec}

    def save(self):
        tmp = self.dir / "state.json.tmp"
        tmp.write_text(json.dumps({"broker": self.broker.to_dict(), "risk_state": asdict(self.rs),
                                   "last_decision_bar": self.last_bar}, indent=1))
        tmp.replace(self.dir / "state.json")


def _fmt(r):
    b, rec = r["broker"], r["record"]
    pos = ", ".join(f"{c} {s:+g}" for c, s in b["positions"].items() if s) or "flat"
    return (f"[{rec['ts'][:19]}Z] {'DECISION' if r['decided'] else 'monitor '} equity ${b['equity']:,.2f} | "
            f"{pos} | orders {len(rec['orders'])} | risk {rec['risk']['notes'] or 'ok'}"
            + (f" | errors {rec['inputs']['notes']}" if rec["inputs"]["notes"] else ""))


def main():
    from hlagent.live.feed import HyperliquidFeed
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["tick", "loop", "status", "kill", "reset-kill"])
    ap.add_argument("--state-dir", default="state")
    a = ap.parse_args()
    cfg = Config(state_dir=a.state_dir)
    sd = Path(a.state_dir)
    if a.cmd == "kill":
        sd.mkdir(exist_ok=True)
        (sd / "KILL").write_text("manual kill\n")
        print("KILL file written; next tick flattens the paper book and latches.")
        return
    agent = Agent(cfg, HyperliquidFeed())
    if a.cmd == "reset-kill":
        (sd / "KILL").unlink(missing_ok=True)
        agent.rs.reset_kill()
        agent.save()
        print("kill reset")
    elif a.cmd == "status":
        b = agent.broker
        print(json.dumps({"strategy": cfg.strategy, "status": cfg.strategy_status, "mode": cfg.mode,
                          "equity": round(b.equity, 2), "start": cfg.start_equity,
                          "pnl_pct": round(100 * (b.equity / cfg.start_equity - 1), 3),
                          "positions": b.positions, "fees_paid": round(b.fees_paid, 2),
                          "funding_paid": round(b.funding_paid, 4), "fills": b.n_fills,
                          "risk": asdict(agent.rs)}, indent=1))
    elif a.cmd == "tick":
        print(_fmt(agent.tick()))
    else:
        print(f"agent loop: mode={cfg.mode} strategy={cfg.strategy} ({cfg.strategy_status}); "
              f"polling every {cfg.poll_s}s, deciding on 4h closes", flush=True)
        while True:
            try:
                print(_fmt(agent.tick()), flush=True)
            except Exception:  # noqa: BLE001 - never die; log and keep monitoring
                traceback.print_exc()
            time.sleep(cfg.poll_s)


if __name__ == "__main__":
    main()
