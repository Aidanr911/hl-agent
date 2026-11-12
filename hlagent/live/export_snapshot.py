"""Export the agent's current state as CSV files for a hosted dashboard.

  python3 -m hlagent.live.export_snapshot --state-dir state --out snapshot/

Writes summary.csv, equity.csv, positions.csv and activity.csv. Read-only.
"""
import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path

from hlagent.live.dashboard import BAR, build_state


def _iso(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write(path, rows, cols):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def export(state_dir: Path, out: Path, start_equity: float = 10_000.0):
    s = build_state(state_dir, max_points=3000, recent=30)
    out.mkdir(parents=True, exist_ok=True)
    b, rs = s["broker"], s["risk_state"]
    eq = b["equity"]
    if rs["killed"]:
        status, note = "Killed", rs["kill_reason"]
    elif rs["halted_until_day"] and rs["day"] < rs["halted_until_day"]:
        status, note = "Halted", f"daily loss limit; resumes {rs['halted_until_day']}"
    else:
        status = "Normal"
        note = (f"today {100 * (eq / rs['day_start_equity'] - 1):+.2f}% (limit -3%), "
                f"from peak {100 * (eq / rs['peak_equity'] - 1):+.2f}% (limit -15%)")
    _write(out / "summary.csv", [{
        "updated_utc": s["last_tick"][:19] + "Z" if s["last_tick"] else "",
        "equity": round(eq, 2), "start_equity": start_equity,
        "pnl": round(eq - start_equity, 2), "pnl_pct": round(100 * (eq / start_equity - 1), 3),
        "fees_paid": round(b["fees_paid"], 2), "funding_paid": round(b["funding_paid"], 2),
        "fills": b["n_fills"], "risk_status": status, "risk_note": note,
        "next_decision_utc": _iso(s["last_decision_bar"] + 2 * BAR),
        "strategy": f"{s['strategy']['name']} {s['strategy'].get('days', '')}d".strip(),
        "strategy_status": s["strategy_status"],
    }], ["updated_utc", "equity", "start_equity", "pnl", "pnl_pct", "fees_paid", "funding_paid", "fills",
         "risk_status", "risk_note", "next_decision_utc", "strategy", "strategy_status"])
    _write(out / "equity.csv", [{"time_utc": p["ts"][:19] + "Z", "equity": round(p["equity"], 2),
                                 "event": "decision" if p["decided"] else "check"} for p in s["curve"]],
           ["time_utc", "equity", "event"])
    rows = []
    for c in b["sz_decimals"]:
        size = b["positions"].get(c, 0.0)
        px = b["marks"].get(c, s["mids"].get(c, 0.0))
        rows.append({"coin": c, "side": "Long" if size > 0 else "Short" if size < 0 else "Flat",
                     "size": abs(size), "price": px, "value": round(abs(size * px), 2),
                     "weight_pct": round(100 * s["weights"].get(c, 0.0), 2)})
    _write(out / "positions.csv", rows, ["coin", "side", "size", "price", "value", "weight_pct"])
    _write(out / "activity.csv", [{"time_utc": r["ts"][:19] + "Z", "type": "Decision" if r["decided"] else "Check",
                                   "equity": round(r["equity"], 2), "orders": "; ".join(r["orders"]),
                                   "risk_notes": "; ".join(r["risk"] + r["errors"])} for r in s["log"]],
           ["time_utc", "type", "equity", "orders", "risk_notes"])
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", default="state")
    ap.add_argument("--out", default="snapshot")
    a = ap.parse_args()
    print(export(Path(a.state_dir), Path(a.out)))
