"""Hard risk limits. Pure code: no strategy or model output can bypass this layer.

Order of precedence (highest first):
  1. kill (kill file or drawdown breach)  -> flatten all, latched until reset_kill()
  2. daily loss breach                     -> flatten all, latched until next UTC day
  3. API error storm                       -> freeze: hold current weights, no new trades
  4. stale data for a coin                 -> freeze that coin
  5. per-position cap, then gross cap      -> clip / scale
"""
from dataclasses import dataclass, field
from datetime import date, timedelta


@dataclass
class Limits:
    max_pos: float = 0.5          # |weight| per coin, fraction of equity
    max_gross: float = 1.0        # sum |weight|
    daily_loss: float = 0.03      # fraction of day-start equity
    max_drawdown: float = 0.15    # fraction of peak equity
    stale_after_s: float = 5 * 3600
    max_api_errors: int = 3


@dataclass
class RiskState:
    day: str
    day_start_equity: float
    peak_equity: float
    killed: bool = False
    kill_reason: str = ""
    halted_until_day: str = ""

    def reset_kill(self):
        self.killed, self.kill_reason = False, ""


@dataclass
class Decision:
    targets: dict
    notes: list = field(default_factory=list)
    flattened: bool = False


class RiskEngine:
    def __init__(self, limits: Limits):
        self.lim = limits

    def check(self, targets, current, equity, state: RiskState, data_age_s, api_errors, kill_file) -> Decision:
        notes = []
        flat = {k: 0.0 for k in targets}
        if kill_file and not state.killed:
            state.killed, state.kill_reason = True, "kill file present"
        dd = 1 - equity / state.peak_equity if state.peak_equity > 0 else 0.0
        if dd >= self.lim.max_drawdown and not state.killed:
            state.killed, state.kill_reason = True, f"drawdown {dd:.1%} >= {self.lim.max_drawdown:.0%}"
        if state.killed:
            return Decision(flat, [f"KILLED: {state.kill_reason} (manual reset required)"], True)

        day_loss = 1 - equity / state.day_start_equity if state.day_start_equity > 0 else 0.0
        if day_loss >= self.lim.daily_loss and not state.halted_until_day:
            state.halted_until_day = (date.fromisoformat(state.day) + timedelta(days=1)).isoformat()
            notes.append(f"daily loss {day_loss:.1%} >= {self.lim.daily_loss:.0%}")
        if state.halted_until_day and state.day < state.halted_until_day:
            return Decision(flat, notes + [f"HALTED until {state.halted_until_day} UTC"], True)
        state.halted_until_day = ""

        if api_errors >= self.lim.max_api_errors:
            return Decision(dict(current), [f"FROZEN: {api_errors} api errors this tick"])

        out = {}
        for k, w in targets.items():
            if data_age_s.get(k, float("inf")) > self.lim.stale_after_s:
                out[k] = current.get(k, 0.0)
                notes.append(f"{k} stale ({data_age_s.get(k)}s): frozen")
                continue
            if abs(w) > self.lim.max_pos:
                notes.append(f"{k} clip {w:+.2f} -> {self.lim.max_pos:+.2f}")
                w = self.lim.max_pos if w > 0 else -self.lim.max_pos
            out[k] = w
        gross = sum(abs(v) for v in out.values())
        if gross > self.lim.max_gross * 1.02:
            f = self.lim.max_gross / gross
            out = {k: v * f for k, v in out.items()}
            notes.append(f"gross {gross:.2f} scaled to {self.lim.max_gross:.2f}")
        return Decision(out, notes)
