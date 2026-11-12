"""Play-money broker. Fills at the live mid, plus slippage and taker fee. No exchange contact."""
import math

MIN_NOTIONAL = 10.0  # Hyperliquid perp minimum order value (USD)


class PaperBroker:
    def __init__(self, equity, fee_bps, slip_bps, sz_decimals, positions=None, marks=None,
                 last_funding_ms=None, fees_paid=0.0, funding_paid=0.0, n_fills=0):
        self.equity = float(equity)
        self.fee_bps, self.slip_bps, self.sz_decimals = fee_bps, dict(slip_bps), dict(sz_decimals)
        self.positions = dict(positions or {})
        self.marks = dict(marks or {})
        self.last_funding_ms = dict(last_funding_ms or {})
        self.fees_paid, self.funding_paid, self.n_fills = fees_paid, funding_paid, n_fills

    def _round(self, coin, size):
        q = 10 ** self.sz_decimals.get(coin, 4)
        return math.trunc(size * q) / q

    def mark(self, mids):
        for coin, size in self.positions.items():
            if coin in mids and coin in self.marks:
                self.equity += size * (mids[coin] - self.marks[coin])
        for coin, px in mids.items():
            self.marks[coin] = px

    def accrue_funding(self, coin, prints, mid):
        last = self.last_funding_ms.get(coin, 0)
        size = self.positions.get(coin, 0.0)
        for t, rate in prints:
            if t > last:
                pay = size * mid * rate          # longs pay positive funding
                self.equity -= pay
                self.funding_paid += pay
                last = t
        self.last_funding_ms[coin] = last

    def rebalance(self, coin, target_size, mid):
        self.mark({coin: mid})
        target = self._round(coin, target_size)
        cur = self.positions.get(coin, 0.0)
        delta = target - cur
        if delta == 0 or (target != 0 and abs(delta) * mid < MIN_NOTIONAL):
            return None
        side = 1 if delta > 0 else -1
        slip = self.slip_bps.get(coin, 0.0)
        cost = abs(delta) * mid * (self.fee_bps + slip) / 1e4
        self.equity -= cost
        self.fees_paid += cost
        self.positions[coin] = target
        self.n_fills += 1
        return {"coin": coin, "side": "buy" if side > 0 else "sell", "size": abs(delta),
                "px": mid * (1 + side * slip / 1e4), "cost": cost, "new_position": target}

    def weights(self):
        return {c: s * self.marks.get(c, 0.0) / self.equity for c, s in self.positions.items()} if self.equity else {}

    def to_dict(self):
        return {"equity": self.equity, "fee_bps": self.fee_bps, "slip_bps": self.slip_bps,
                "sz_decimals": self.sz_decimals, "positions": self.positions, "marks": self.marks,
                "last_funding_ms": self.last_funding_ms, "fees_paid": self.fees_paid,
                "funding_paid": self.funding_paid, "n_fills": self.n_fills}

    @classmethod
    def from_dict(cls, d):
        return cls(**d)
