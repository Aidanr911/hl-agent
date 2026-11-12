"""Local read-only dashboard for the play-money agent.

  python3 -m hlagent.live.dashboard --port 8765 [--state-dir state]

Serves dashboard.html and /api/state (built from state/state.json + state/journal.jsonl).
It only reads files; it cannot change positions (use the agent CLI's `kill` for that).
"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).parent
BAR = 4 * 3_600_000


def build_state(state_dir: Path, max_points: int = 2000, recent: int = 15) -> dict:
    s = json.loads((state_dir / "state.json").read_text())
    rows = []
    jp = state_dir / "journal.jsonl"
    if jp.exists():
        for line in jp.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    curve = [{"ts": r["ts"], "equity": r["result"]["equity"], "decided": r["decided"]} for r in rows]
    if len(curve) > max_points:
        step = len(curve) / max_points
        curve = [curve[int(i * step)] for i in range(max_points)] + [curve[-1]]
    last = rows[-1] if rows else {}
    log = [{
        "ts": r["ts"], "decided": r["decided"], "equity": r["result"]["equity"],
        "orders": [f"{o['side']} {o['size']:g} {o['coin']}" for o in r["orders"]],
        "risk": r["risk"]["notes"], "errors": r["inputs"]["notes"],
    } for r in rows[-recent:]][::-1]
    return {
        "strategy": last.get("strategy"), "strategy_status": last.get("strategy_status"),
        "mode": last.get("mode"), "broker": s["broker"], "risk_state": s["risk_state"],
        "last_decision_bar": s["last_decision_bar"], "mids": last.get("inputs", {}).get("mids", {}),
        "weights": last.get("result", {}).get("weights_after", {}),
        "last_tick": last.get("ts"), "curve": curve, "log": log,
        "kill_file": (state_dir / "KILL").exists(),
    }


def make_handler(state_dir: Path):
    class H(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            if self.path.startswith("/api/state"):
                try:
                    self._send(200, json.dumps(build_state(state_dir), default=float).encode(), "application/json")
                except FileNotFoundError:
                    self._send(503, b'{"error":"agent has not run yet"}', "application/json")
            elif self.path in ("/", "/index.html"):
                self._send(200, (HERE / "dashboard.html").read_bytes(), "text/html; charset=utf-8")
            else:
                self._send(404, b"not found", "text/plain")

        def log_message(self, *a):
            pass
    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--state-dir", default="state")
    a = ap.parse_args()
    srv = ThreadingHTTPServer((a.host, a.port), make_handler(Path(a.state_dir)))
    print(f"dashboard on http://localhost:{a.port}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
