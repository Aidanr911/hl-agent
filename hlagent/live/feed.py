"""Read-only Hyperliquid mainnet market data via the public /info endpoint. Never signs anything."""
import json
import time
import urllib.request

import pandas as pd

INFO_URL = "https://api.hyperliquid.xyz/info"
BAR = 4 * 3_600_000


class HyperliquidFeed:
    def __init__(self, url=INFO_URL, timeout=10.0):
        self.url, self.timeout = url, timeout

    def _post(self, body):
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read())

    def now_ms(self):
        return int(time.time() * 1000)

    def meta(self):
        return {a["name"]: a["szDecimals"] for a in self._post({"type": "meta"})["universe"]}

    def mids(self):
        return {k: float(v) for k, v in self._post({"type": "allMids"}).items()}

    def candles(self, coin, n):
        """Last n CLOSED 4h candles."""
        now = self.now_ms()
        rows = self._post({"type": "candleSnapshot", "req": {
            "coin": coin, "interval": "4h", "startTime": now - (n + 2) * BAR, "endTime": now}})
        df = pd.DataFrame([{"t": int(r["t"]), "T": int(r["T"]), "o": float(r["o"]), "h": float(r["h"]),
                            "l": float(r["l"]), "c": float(r["c"]), "v": float(r["v"])} for r in rows])
        df = df[df["T"] < now].drop(columns="T").set_index("t").sort_index()
        return df.tail(n)

    def funding(self, coin, since_ms):
        rows = self._post({"type": "fundingHistory", "coin": coin, "startTime": int(since_ms) + 1})
        return [(int(r["time"]), float(r["fundingRate"])) for r in rows]
