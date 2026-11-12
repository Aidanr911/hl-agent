"""Run the pre-registered protocol in docs/SPEC.md and write reports/results.{json,md}."""
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd

from hlagent import data, engine, metrics, sizing, strategies

ROOT = Path(__file__).parent
SYMS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
SLIP_BPS = {"BTC": 2.0, "ETH": 2.0, "SOL": 4.0, "XRP": 4.0, "DOGE": 4.0}
TAKER_BPS = 4.5


def ms(s):
    return int(pd.Timestamp(s, tz="UTC").timestamp() * 1000)


# Train starts 2025-02-01, not 2024-11-01: the longest lookback (90d) plus the 30d vol estimate
# needs warm-up, and every variant must be judged on the same window.
TRAIN = (ms("2025-02-01"), ms("2026-04-01"))
HOLDOUT = (ms("2026-04-01"), ms("2026-11-12"))

GRIDS = {
    "S1 tsmom L/S": ("tsmom", [{"days": d} for d in (5, 10, 20, 30, 60, 90)]),
    "S2 tsmom long-only": ("tsmom_long", [{"days": d} for d in (5, 10, 20, 30, 60, 90)]),
    "S3 donchian": ("donchian", [{"n": n} for n in (20, 40, 60, 120, 180)]),
    "S4 funding contrarian": ("funding", [{"days": d, "thresh": t} for d in (1, 3) for t in (0.2, 0.3, 0.5)]),
    "S5 mean reversion": ("meanrev", [{"n": n, "k": k} for n in (12, 30, 60) for k in (1.5, 2.0, 2.5)]),
    "S6 cross-sectional mom": ("xsec", [{"days": d} for d in (3, 7, 14, 30, 60)]),
}


def neighbours(params, i):
    """Grid neighbours: adjacent along any one parameter axis."""
    keys = list(params[0])
    axes = {k: sorted({p[k] for p in params}) for k in keys}
    me = params[i]
    out = []
    for j, p in enumerate(params):
        diff = [abs(axes[k].index(p[k]) - axes[k].index(me[k])) for k in keys]
        if sum(diff) == 1:
            out.append(j)
    return out


def load():
    candles, funding = {}, {}
    for s in SYMS:
        candles[s], funding[s] = data.load_bundle(ROOT / "data" / f"{s.lower()}-4h")
    return candles, funding


def targets(kind, p, candles, funding):
    if kind == "xsec":
        raw = strategies.cross_sectional(candles, days=p["days"])
        return pd.DataFrame({s: sizing.vol_target(raw[s], candles[s]) for s in SYMS})
    if kind == "bench":
        return pd.DataFrame({s: pd.Series(0.2, index=candles[s].index) for s in SYMS})
    return pd.DataFrame({s: sizing.vol_target(strategies.signal(kind, candles[s], funding[s], **p), candles[s])
                         for s in SYMS})


def window_stats(res, win):
    idx = res.returns.index
    m = (idx >= win[0]) & (idx < win[1])
    r = res.returns[m]
    eq = (1 + r).cumprod()
    tr = metrics.trades_from(res.weights[m], res.contrib[m])
    years = m.sum() / metrics.PERIODS
    out = {
        "sharpe": metrics.sharpe(r),
        "cagr": float(eq.iloc[-1] ** (1 / years) - 1),
        "total_return": float(eq.iloc[-1] - 1),
        "max_dd": metrics.max_drawdown(pd.concat([pd.Series([1.0]), eq])),
        "turnover_per_year": float(res.turnover[m].sum() / years),
        "skew": float(r.skew()), "kurt": float(r.kurt() + 3), "n_obs": int(m.sum()),
    }
    out.update(metrics.trade_stats(tr))
    return out


def run_variant(kind, p, candles, funding, cost_mult=1.0):
    t = targets(kind, p, candles, funding)
    cost = {s: cost_mult * (TAKER_BPS + SLIP_BPS[s]) for s in SYMS}
    return engine.run(candles, funding, t, cost_bps=cost, band=0.2)


def main():
    candles, funding = load()
    results, all_train_sr = {}, []
    for name, (kind, grid) in GRIDS.items():
        rows = []
        for p in grid:
            res = run_variant(kind, p, candles, funding)
            rows.append({"params": p, "train": window_stats(res, TRAIN)})
            all_train_sr.append(rows[-1]["train"]["sharpe"])
        for i, row in enumerate(rows):
            nb = [i] + neighbours(grid, i)
            row["nbhd_sharpe"] = float(np.mean([rows[j]["train"]["sharpe"] for j in nb]))
        best = max(range(len(rows)), key=lambda i: rows[i]["nbhd_sharpe"])
        results[name] = {"kind": kind, "grid": rows, "chosen": best}

    n_trials = len(all_train_sr)
    sr_var = float(np.var(all_train_sr, ddof=1))
    for name, r in results.items():
        row = r["grid"][r["chosen"]]
        p = row["params"]
        tr = row["train"]
        row["dsr"] = metrics.deflated_sharpe(tr["sharpe"], tr["n_obs"], n_trials, sr_var, tr["skew"], tr["kurt"])
        row["n_positive_train"] = sum(g["train"]["sharpe"] > 0 for g in r["grid"])
        # holdout: touched once, at 1x/2x/3x costs
        row["holdout"] = {f"{m}x": window_stats(run_variant(r["kind"], p, candles, funding, m), HOLDOUT)
                          for m in (1, 2, 3)}
        h1, h2 = row["holdout"]["1x"], row["holdout"]["2x"]
        checks = {
            "train_nbhd_sharpe>=0.5": row["nbhd_sharpe"] >= 0.5,
            "holdout_sharpe>=0.5": h1["sharpe"] >= 0.5,
            "holdout_sharpe_2x_cost>0": h2["sharpe"] > 0,
            "holdout_maxdd<=25%": h1["max_dd"] <= 0.25,
            "holdout_trades>=30": h1["trades"] >= 30,
            "dsr>=0.90": row["dsr"] >= 0.90,
            "not_single_point": row["n_positive_train"] >= 2,
        }
        row["checks"] = checks
        if all(checks.values()):
            v = "PASS"
        elif h1["sharpe"] > 0 and checks["not_single_point"]:
            v = "WATCH"
        else:
            v = "REJECT"
        row["verdict"] = v

    bench = run_variant("bench", {}, candles, funding)
    results["B0 equal-weight buy&hold"] = {"benchmark": True,
                                          "train": window_stats(bench, TRAIN),
                                          "holdout": window_stats(bench, HOLDOUT)}
    meta = {"n_trials": n_trials, "train_sharpe_var": sr_var,
            "train": [str(pd.Timestamp(x, unit="ms")) for x in TRAIN],
            "holdout": [str(pd.Timestamp(x, unit="ms")) for x in HOLDOUT]}
    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    (out / "results.json").write_text(json.dumps({"meta": meta, "results": results}, indent=1, default=float))
    print_table(meta, results)


def print_table(meta, results):
    print(f"variants tried: {meta['n_trials']}  train {meta['train']}  holdout {meta['holdout']}")
    hdr = "| Strategy | Chosen params | Train nbhd SR | Train SR | DSR | Holdout SR | SR @2x | SR @3x | Holdout MaxDD | Holdout ret | Trades | Win% | PF | Verdict |"
    print(hdr)
    print("|" + "---|" * hdr.count("|")[:-1] if False else "|---" * (hdr.count("|") - 1) + "|")
    for name, r in results.items():
        if r.get("benchmark"):
            h = r["holdout"]
            print(f"| {name} | — | — | {r['train']['sharpe']:.2f} | — | {h['sharpe']:.2f} | — | — | {h['max_dd']:.1%} | {h['total_return']:+.1%} | — | — | — | benchmark |")
            continue
        row = r["grid"][r["chosen"]]
        h = row["holdout"]
        print(f"| {name} | {row['params']} | {row['nbhd_sharpe']:.2f} | {row['train']['sharpe']:.2f} | "
              f"{row['dsr']:.2f} | {h['1x']['sharpe']:.2f} | {h['2x']['sharpe']:.2f} | {h['3x']['sharpe']:.2f} | "
              f"{h['1x']['max_dd']:.1%} | {h['1x']['total_return']:+.1%} | {h['1x']['trades']} | "
              f"{h['1x']['win_rate']:.0%} | {h['1x']['profit_factor']:.2f} | {row['verdict']} |")
    print()
    for name, r in results.items():
        if r.get("benchmark"):
            continue
        print(name, " ".join(f"{g['params']}:{g['train']['sharpe']:.2f}" for g in r["grid"]))
        print("   failed:", [k for k, v in r["grid"][r["chosen"]]["checks"].items() if not v])


if __name__ == "__main__":
    main()
