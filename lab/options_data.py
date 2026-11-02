"""Real option quotes recorded by the nightly data job (data/options/<date>/<SYM>.csv).

Use these — never modelled prices — for any options idea. Fills are pessimistic by default:
buy at the ask, sell at the bid. Quotes are one snapshot per trading day (~3:30 PM New York).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

OPT = Path(__file__).resolve().parent.parent / "data" / "options"


def snapshot_dates() -> list[str]:
    return sorted(p.name for p in OPT.iterdir() if p.is_dir()) if OPT.exists() else []


def load_chain(date: str, symbol: str) -> pd.DataFrame:
    """All recorded quotes for one symbol on one date (calls and puts, expiries ≤ 60 days)."""
    f = OPT / date / f"{symbol}.csv"
    return pd.read_csv(f) if f.exists() else pd.DataFrame()


def load_all(symbol: str) -> pd.DataFrame:
    frames = []
    for d in snapshot_dates():
        c = load_chain(d, symbol)
        if not c.empty:
            frames.append(c.assign(date=d))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def quote(df: pd.DataFrame, date: str, kind: str, expiry: str, strike: float) -> pd.Series | None:
    """The recorded quote for one contract on one date, or None if it wasn't recorded."""
    q = df[(df.date == date) & (df.type == kind) & (df.expiry == expiry) & (df.strike == strike)]
    return None if q.empty else q.iloc[0]


def coverage() -> dict:
    d = snapshot_dates()
    return {"days_recorded": len(d), "first": d[0] if d else None, "last": d[-1] if d else None}
