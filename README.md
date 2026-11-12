# hl-agent

A disarmed, play-money trading agent for Hyperliquid perpetuals, plus the research that decides what it
is allowed to trade.

**It cannot place real orders.** There is no code that signs or sends anything to an exchange, and a
test (`test_agent_has_no_live_order_path`) fails if any is added. It trades a simulated $10,000 account
at live Hyperliquid prices, with fees, slippage and funding.

## Status

- Phase 1 research: 37 strategy variants tested, **all rejected**. See [`docs/REPORT.md`](docs/REPORT.md).
- The agent runs the rejected 90-day momentum strategy in shadow mode to exercise the machinery.
  Expect it to lose money.

## Run

Python 3.10+.

```bash
pip install numpy pandas pytest
python3 -m pytest -q tests              # 32 tests
python3 -m hlagent.live.agent loop      # run continuously (polls 5 min, decides on 4h closes)
python3 -m hlagent.live.agent status    # equity, positions, fees, risk state
python3 -m hlagent.live.agent kill      # flatten the paper book and latch
python3 -m hlagent.live.agent reset-kill
python3 research.py                     # reproduce the backtest report
```

State and the decision journal are written to `state/` (not committed).

## Risk limits (enforced in `hlagent/risk.py`)

| Limit | Value | Action |
|---|---|---|
| Per-coin position | 50% of equity | clip |
| Gross exposure | 100% of equity | scale down |
| Daily loss | 3% | flatten, halt until next UTC day |
| Drawdown from peak | 15% | flatten, latched until manual reset |
| Kill file / `kill` command | — | flatten, latched until manual reset |
| Stale data | per coin | freeze that coin |
| API errors | 3 per cycle | freeze all trading |

## Layout

```
hlagent/            data, engine, strategies, sizing, metrics, risk
hlagent/live/       feed (read-only public API), paper broker, agent loop
tests/              engine, risk and agent tests
data/               verified Hyperliquid 4h candles + funding (HyperGrok research bundles)
docs/SPEC.md        venue, regime, strategies, pre-registered pass/fail rules
docs/REPORT.md      results, bear case, "How could this system fail?"
```

Not financial advice.

## Dashboard

```bash
python3 -m hlagent.live.dashboard --port 8765   # then open http://localhost:8765
```

Read-only page: equity curve, positions, holdings, risk status, next decision and recent activity.
Refreshes every 15 seconds from `state/`.
