# hl-agent: Phase 1 research report (2026-11-12)

## Verdict: no strategy passed. Nothing goes to paper trading.

All six candidate families (37 variants) were tested under the rules fixed in `SPEC.md` before any
backtest ran. All six were **rejected**. The protocol did its job: it stopped us from deploying a weak
strategy into a live 24/7 bot.

## System overview

- **Venue:** Hyperliquid perps (BTC, ETH, SOL, XRP, DOGE), 24/7, taker 4.5 bps, hourly funding.
- **Regime now:** broad drawdown (30-day −10% to −22%), alts below their 200-day average, volatility below
  its 2-year norm, funding mildly positive (not crowded).
- **Approach:** 4h bar-close signals, volatility-targeted sizing, taker execution with slippage, funding
  charged hourly. Train Feb 2025 → Mar 2026, one-shot holdout Apr → Nov 2026.

## Comparison table

Real backtests on verified Hyperliquid data. Costs = taker 4.5 bps + slippage 2–4 bps per side, plus funding.
SR = annualised Sharpe. "Nbhd" = the chosen setting averaged with its grid neighbours.

| Strategy | Edge | Market | Timeframe | Chosen | Train nbhd SR | Holdout SR | SR @2× / 3× cost | Holdout max DD | Holdout trades | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| S1 Time-series momentum L/S | trends persist | 5 perps | 4h, days–weeks | 90d | 0.49 | **−1.62** | −1.72 / −1.82 | 55% | 83 | REJECT |
| S2 Momentum long-only | same, longs only | 5 perps | 4h | 90d | −0.32 | −1.25 | −1.33 / −1.40 | 39% | 41 | REJECT |
| S3 Donchian breakout | range breaks start trends | 5 perps | 4h | 40 bars | −0.19 | 0.48 | 0.32 / 0.17 | 37% | 102 | REJECT |
| S4 Funding contrarian | fade crowded leverage | 5 perps | 4h, days | 1d / 20% | 0.10 | −1.18 | −1.30 / −1.42 | 7% | 12 | REJECT |
| S5 Mean reversion | 4h overshoots revert | 5 perps | 4h, hours | 30 / 2.5σ | −0.14 | −0.88 | −1.11 / −1.34 | 50% | 126 | REJECT |
| S6 Cross-sectional momentum | winners keep winning | 5 perps | daily | 14d | −0.25 | −0.59 | −1.34 / −2.07 | 18% | 137 | REJECT |
| B0 Equal-weight buy & hold | beta | 5 perps | — | — | (train −0.72) | −0.19 | — | 32% | — | benchmark |

Variants tried: **37**. Deflated Sharpe Ratio of every chosen setting: 0.04–0.20 (needed ≥ 0.90), so none of
the train results is distinguishable from luck after counting the trials.

Full per-variant numbers: `reports/results.json`; reproduce with `python3 research.py`.

### What each result says

- **S1 is the closest call, and the clearest warning.** 60–90 day momentum was the only region with a
  positive train Sharpe (~0.5). In the holdout it lost 53% because prices went sideways: the 90-day
  return flipped sign 14–20 times per coin and each flip paid for a whipsaw. An independent recompute
  (unit size, no engine) confirms losses on all five coins. A strategy that is "fine on train, −1.6 on
  holdout" is exactly the overfit-to-one-regime outcome the protocol is there to catch.
- **S3** was the only holdout-positive strategy (+7%, SR 0.48), but it lost money in training at every
  setting and has a 37% drawdown. That is noise, not an edge.
- **S4** made few trades (12) because funding rarely reached ±20% annualised; too little evidence either way.
- **S5** wins often (71%) but loses big: classic short-volatility profile, killed by cost and trends.
- **S6** with 5 coins is too small a universe; it is also the most cost-sensitive (SR −0.59 → −2.07 at 3×).

## Bear case (applies even to a future PASS)

- **Survivorship:** the 5 coins were picked today because they are big today. Delisted or faded coins are absent.
- **One regime:** two years of data = one bull leg, one long drawdown. Any edge found is regime-conditional.
- **Costs:** slippage is assumed, not measured; today's book depth is not historical depth. Stops fill
  worse than candle closes in fast markets.
- **Funding model:** hourly rate × candle close is a proxy; real payments use the oracle price.
- **Bar-close fills:** no intrabar path, so stops and liquidation risk are understated.
- **Crowding:** the strategies tested are textbook; others run them, which is part of why they are weak.

## What I recommend next (needs your approval)

1. **Do not build the live engine yet.** There is no strategy for it to run.
2. **Option A: second research round, better data.** Hyperliquid only serves ~5,000 recent candles per
   market, which limits history. Extending with longer Binance/Bybit perp history (needs those hosts
   allowed) would test the same ideas across 2020–2026, i.e. several regimes. Same pre-registered rules.
3. **Option B: regime gating.** Test S1 only when a trend filter (e.g. the macro/breadth posture we built
   earlier, or realised-vol regime) says trends are likely. This is one new hypothesis, counted as new trials.
4. **Option C: build the risk/kill-switch layer anyway**, as a standalone, tested module (position caps,
   daily loss stop, stale-data halt, flatten-all), so it is ready when a strategy passes. No orders.

## Build plan (when a strategy passes)

```
hl-agent/
  hlagent/            data.py  engine.py  strategies.py  sizing.py  metrics.py   (done, tested)
  hlagent/risk.py     hard limits enforced in code; no model can override        (next)
  hlagent/live/       feed.py (WS + staleness), executor.py (testnet only), killswitch.py, journal.py
  tests/              15 tests now; risk tests next (limit breach, stale data, API error storm)
  docs/               SPEC.md  REPORT.md
  research.py         reproduces this report
```

First module to build: `hlagent/risk.py`, test-first. Paper trading would run on Hyperliquid **testnet**
with a testnet-only API wallet, and would require your approval of a written PASS first.

## HOW COULD THIS SYSTEM FAIL?

1. **Overfitting through the back door.** Running more and more research rounds until something passes is
   the same as data-mining. Every round's trials must be added to the count, and the holdout is now spent:
   **April–November 2026 can no longer be used as an unseen test.** The next round needs fresh
   out-of-sample data (paper trading forward) as its final judge.
2. **Regime change.** The one family that looked good in training lost 53% when the market went sideways.
   Any future PASS must show it survives a sideways regime, or be gated to switch off in one.
3. **Costs and liquidity.** A 2–3× cost shock turned the best holdout result (S3) from SR 0.48 to 0.17.
   Edges in this space are thin; real fills, outages and liquidation cascades eat them.
4. **Data or exchange failure.** If the Hyperliquid API or feed stalls, a 24/7 bot holding a position is
   blind. Required before any live run: stale-data halt, mark/oracle divergence halt, resting exchange-side
   stop on every position, and a kill switch tested on testnet.
5. **Operator risk.** A 24/7 agent with keys can do damage fastest when something unexpected happens.
   Keys stay testnet-only; mainnet needs your explicit approval per the spec; the agent never moves funds.
6. **The edge may already be gone.** Simple crypto trend and carry ideas are widely traded; the weak
   results here are consistent with that. Survival over an impressive backtest: the correct output of
   this phase is "don't trade yet."
