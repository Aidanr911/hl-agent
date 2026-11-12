# hl-agent: Spec (Phase 1)

Status: **draft for approval**. Research only. Nothing in this repo signs, sends or holds keys.

## 1. Market and venue

| Item | Value | Source |
|---|---|---|
| Asset class | USDC-margined perpetual futures (crypto) | |
| Venue | Hyperliquid mainnet (paper trading later on Hyperliquid testnet) | |
| Universe (research) | BTC, ETH, SOL, XRP, DOGE | chosen for depth; **not survivorship-free** |
| Trading hours | 24/7 | |
| Fees (base tier) | taker 0.045%, maker 0.015% per side | HyperGrok `hyperliquid-api-reference` |
| Funding | paid hourly; longs pay when rate > 0 | Hyperliquid `fundingHistory` |
| Min order value | $10 notional | HyperGrok `hyperliquid-api-reference` |
| Max leverage (exchange) | BTC 40x, ETH 25x, SOL 20x, XRP 20x, DOGE 10x | `/info meta`, 2026-11-12 |
| REST limits | 1200 weight/min per IP; address action budget 10,000 + 1 per $1 volume | HyperGrok reference |
| Latency need | low: signals on 4h bar closes; seconds of delay are irrelevant | design choice |

**Data:** 4h candles and hourly funding, 2024-11-01 → 2026-11-12 UTC, collected with HyperGrok
`research_dataset.py`. All five bundles report `complete` coverage (4,446 candles, 17,784 funding prints
each) and pass offline `--verify`.

## 2. Current regime (2026-11-12, computed from the data above)

| | BTC | ETH | SOL | XRP | DOGE |
|---|---|---|---|---|---|
| 30-day change | −9.6% | −16.0% | −21.2% | −21.6% | −17.9% |
| vs 200-day average | above | below | below | below | below |
| Realised vol, last 30d (ann.) | 39% | 57% | 59% | 56% | 59% |
| Funding, last 7d (ann.) | +10.5% | +7.4% | +1.6% | +5.5% | +0.9% |

Read: broad drawdown with alts weaker than BTC, volatility below its 2-year average, funding positive
but not extreme (longs are not crowded). The US equity check run the same day was REDUCE_ONLY.

**Trade / stay out conditions (to be enforced in code):**
- Stay out of a market when its data is stale (> 2 bars late), its 24h volume falls below $50M, or the
  visible book within 25 bps cannot absorb 5× the intended order.
- Halt new entries around exchange incidents (API error rate limit breached, mark/oracle divergence > 1%).

## 3. Candidate strategies

All signals are computed at a 4h bar close using only data up to that close, and executed at that close
plus costs (no intrabar fills assumed). Signals are separate from sizing and execution.

| # | Strategy | Edge in one sentence | Who is on the other side |
|---|---|---|---|
| S1 | Time-series momentum, long/short | Crypto trends persist because information and flows (leverage, liquidations, retail chasing) arrive slowly. | Mean-reverting traders, hedgers, late sellers |
| S2 | Time-series momentum, long-only | Same, but only participates in up-trends; avoids paying for short squeezes. | Same |
| S3 | Donchian breakout | Breaks of multi-week ranges start trends that stops and liquidations accelerate. | Range traders, short-volatility sellers |
| S4 | Funding contrarian | When funding is extreme, leveraged crowd positioning tends to unwind; fading it also collects funding. | Over-leveraged directional traders paying funding |
| S5 | Short-term mean reversion | Overshoots on 4h bars partially revert as liquidity providers step in. | Liquidated / panicking traders |
| S6 | Cross-sectional momentum | Coins that outperformed peers keep outperforming for weeks (attention and flows). | Rotators buying laggards |
| B0 | Benchmark: equal-weight buy-and-hold | Market beta, no skill. | — |

Parameter grids (every variant is counted):

| # | Rules | Grid |
|---|---|---|
| S1 | sign of trailing L-day return | L ∈ {5, 10, 20, 30, 60, 90} days |
| S2 | long if trailing L-day return > 0 else flat | L ∈ {5, 10, 20, 30, 60, 90} days |
| S3 | long on close > N-bar high, short on close < N-bar low, exit at opposite N/2-bar channel | N ∈ {20, 40, 60, 120, 180} bars |
| S4 | mean funding over W days; short if > +T, long if < −T (annualised), else flat | W ∈ {1, 3} days × T ∈ {20%, 30%, 50%} |
| S5 | z = (close − SMA N)/stdev N; long z < −k, short z > k, exit when z crosses 0 | N ∈ {12, 30, 60} bars × k ∈ {1.5, 2.0, 2.5} |
| S6 | rank by trailing L-day return, long top 2 / short bottom 2, rebalance daily | L ∈ {3, 7, 14, 30, 60} days |

Holding period / frequency: S1–S3 days to weeks; S4 days; S5 hours to a day; S6 daily rebalance.

## 4. Sizing and cost model (backtest)

- Volatility targeting: per-asset weight = signal × min(0.5, 0.15 / σ̂), σ̂ = 30-day EWMA realised vol
  (annualised) known at the bar close. Never full Kelly.
- Rebalance band: only trade when the target differs from the held weight by > 20% of the target, or the
  sign changes.
- Costs per unit turnover: taker 4.5 bps + slippage 2 bps (BTC, ETH) / 4 bps (SOL, XRP, DOGE).
  Sensitivity at 2× and 3× costs.
- Funding: each hourly rate × held weight, charged to longs when positive (rate × candle-close proxy; true
  payments use oracle price at payment time).

## 5. Validation protocol (pre-registered, written before any backtest was run)

- **Train:** 2024-11-01 → 2026-03-31. **Holdout:** 2026-04-01 → 2026-11-12 (touched once per strategy).
- Choose each strategy's parameter on train only, by the best **neighbourhood-average** Sharpe (the
  setting averaged with its grid neighbours), not the best single setting.
- Report Sharpe, max drawdown, win rate, profit factor, trades, and the count of all variants tried.
  Deflated Sharpe Ratio (Bailey & López de Prado) over all variants judges the train result against chance.
- **PASS** (eligible for paper trading) requires *all* of: train neighbourhood Sharpe ≥ 0.5; holdout
  Sharpe ≥ 0.5 net of costs; holdout Sharpe > 0 at 2× costs; holdout max drawdown ≤ 25%; ≥ 30 trades in
  holdout; DSR ≥ 0.90.
- **WATCH**: holdout Sharpe > 0 but fails another PASS rule. **REJECT**: everything else.
- A strategy that only works at one grid point is rejected regardless of its best number.
