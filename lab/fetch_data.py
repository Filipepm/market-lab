"""Nightly market data feed for the Research Lab (public data only, no keys).

Writes:
  data/prices/<SYMBOL>.csv          full daily history (Date,Open,High,Low,Close — split/dividend adjusted)
  data/options/<YYYY-MM-DD>/<SYM>.csv   one snapshot of real option quotes (bid/ask/IV/volume/OI),
                                        taken between 3:00 and 4:00 PM New York time on trading days
  data/status.json                  last update time, symbols, any failures

Run by .github/workflows/data.yml. Safe to re-run: prices are re-downloaded in full, option
snapshots are written once per day.
"""
import datetime as dt
import json
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
PRICES = ROOT / "data" / "prices"
OPTIONS = ROOT / "data" / "options"
NY = ZoneInfo("America/New_York")

SYMBOLS = [
    # US equity indexes
    "SPY", "QQQ", "IWM", "DIA", "MDY", "VTI", "RSP",
    # international
    "EFA", "EEM",
    # bonds, cash-like, credit
    "TLT", "IEF", "SHY", "LQD", "HYG",
    # real assets / currency
    "GLD", "SLV", "USO", "UUP", "VNQ",
    # sectors
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "SMH",
    # leveraged (for strategies that hold them)
    "SSO", "UPRO", "QLD", "TQQQ",
    # indexes and rates (long history)
    "^GSPC", "^VIX", "^VIX3M", "^IRX", "^TNX",
]
OPTION_SYMBOLS = ["SPY", "QQQ", "IWM", "AAPL", "NVDA", "TSLA"]
MAX_EXPIRY_DAYS = 60
STRIKE_BAND = 0.20   # keep strikes within ±20% of the stock price


def fname(sym):
    return sym.replace("^", "_")


def fetch_prices(status):
    PRICES.mkdir(parents=True, exist_ok=True)
    for sym in SYMBOLS:
        for attempt in range(3):
            try:
                df = yf.download(sym, period="max", auto_adjust=True, progress=False,
                                 threads=False, multi_level_index=False)
                if df.empty:
                    raise ValueError("empty")
                df = df[["Open", "High", "Low", "Close"]].dropna(how="all")
                df.index.name = "Date"
                df.round(6).to_csv(PRICES / f"{fname(sym)}.csv")
                status["prices"][sym] = str(df.index[-1].date())
                break
            except Exception as e:  # noqa: BLE001
                if attempt == 2:
                    status["failures"].append(f"{sym}: {e}")
                time.sleep(3)


def snapshot_options(status, now):
    day_dir = OPTIONS / now.date().isoformat()
    if day_dir.exists():
        status["options"] = "already taken today"
        return
    if now.weekday() >= 5 or not (15 <= now.hour < 16):
        status["options"] = f"skipped (NY time {now:%H:%M}, snapshot window is 15:00-16:00 on weekdays)"
        return
    day_dir.mkdir(parents=True, exist_ok=True)
    taken = []
    for sym in OPTION_SYMBOLS:
        try:
            tk = yf.Ticker(sym)
            spot = float(tk.fast_info["last_price"])
            rows = []
            for exp in tk.options:
                dte = (dt.date.fromisoformat(exp) - now.date()).days
                if dte < 0 or dte > MAX_EXPIRY_DAYS:
                    continue
                ch = tk.option_chain(exp)
                for kind, frame in (("call", ch.calls), ("put", ch.puts)):
                    f = frame[(frame.strike >= spot * (1 - STRIKE_BAND)) & (frame.strike <= spot * (1 + STRIKE_BAND))]
                    f = f.assign(type=kind, expiry=exp, dte=dte, spot=spot)
                    rows.append(f[["type", "expiry", "dte", "strike", "bid", "ask", "lastPrice",
                                   "impliedVolatility", "volume", "openInterest", "spot"]])
            if rows:
                out = pd.concat(rows)
                out.insert(0, "taken_at", now.isoformat(timespec="minutes"))
                out.to_csv(day_dir / f"{sym}.csv", index=False)
                taken.append(sym)
        except Exception as e:  # noqa: BLE001
            status["failures"].append(f"options {sym}: {e}")
    status["options"] = f"snapshot of {', '.join(taken)}" if taken else "snapshot failed"


def main():
    now = dt.datetime.now(NY)
    status = {"updated_at": now.isoformat(timespec="minutes"), "prices": {}, "options": "", "failures": []}
    fetch_prices(status)
    snapshot_options(status, now)
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data" / "status.json").write_text(json.dumps(status, indent=2))
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
