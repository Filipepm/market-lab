"""Research Lab engine — the fixed testing gauntlet every strategy idea goes through.

The research agent writes a strategy as a Python function, registers it (rules written down first),
then calls `evaluate(...)`. The gauntlet itself never changes from run to run, so results stay
comparable and the agent cannot quietly loosen the bar.

Strategy shapes
---------------
1. Single-asset exposure:   def exposure(df: DataFrame[Open,High,Low,Close], ctx) -> Series
   Daily exposure decided at the close (0 = cash, 1 = fully invested, 2 = 2x with financing cost).
   Applied from the next day. Tested on SPY, then on 8 other indexes and on the S&P 500 1950–1992.
2. Multi-asset weights:     def weights(prices: DataFrame[symbols -> Close], ctx) -> DataFrame
   Daily weights per symbol (rows sum ≤ 1; the rest earns T-bills; > 1 means leverage).
ctx gives helpers: ctx.rf (daily T-bill series), ctx.rsi(series, n), ctx.sma(series, n).

The gauntlet (PASS needs every check)
-------------------------------------
- dev:        better Sharpe than buy & hold on 1993–2018 (or the symbol's start)
- significance: block-bootstrap p-value of the daily excess return on dev below a bar that gets
              stricter as more ideas are tested: alpha = 0.05 / (1 + ln(ideas_tested))
- holdout:    better Sharpe than buy & hold on 2019 → today (looked at once, recorded)
- breadth:    beats buy & hold Sharpe on ≥ 6 of 8 other indexes (single-asset only)
- deep history: on the S&P 500 1950–1992 not worse than buy & hold Sharpe − 0.05 (single-asset only)
- costs:      still beats buy & hold Sharpe with 4× trading costs
- survival:   chance of a ≥50% loss within a year (block bootstrap) under 5%

Every result also reports CAGR, max drawdown, worst year, trades per year and exposure.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data" / "prices"
DEV_END = "2019-01-01"
DEV_START = "1993-01-01"
OTHERS = ["QQQ", "IWM", "DIA", "MDY", "EFA", "EEM", "VTI", "RSP"]
COST = 0.0005          # 5 bps per unit of exposure traded
LEV_EXPENSE = 0.009    # per year, on exposure above 1x
BLOCK = 20
N_BOOT = 2000


# ------------------------------------------------------------------ data
_cache: dict[str, pd.DataFrame] = {}


def load(symbol: str) -> pd.DataFrame:
    if symbol not in _cache:
        f = DATA / f"{symbol.replace('^', '_')}.csv"
        if not f.exists():
            raise FileNotFoundError(f"no data file for {symbol} ({f})")
        _cache[symbol] = pd.read_csv(f, index_col="Date", parse_dates=True).sort_index()
    return _cache[symbol]


def closes(symbols) -> pd.DataFrame:
    return pd.DataFrame({s: load(s)["Close"] for s in symbols})


def tbill(index) -> pd.Series:
    """Daily T-bill return from ^IRX (13-week yield, %); 2%/yr where missing."""
    try:
        irx = load("^IRX")["Close"].reindex(index).ffill()
    except FileNotFoundError:
        irx = pd.Series(np.nan, index=index)
    return (irx.fillna(2.0) / 100 / 252).clip(lower=0)


# ------------------------------------------------------------------ helpers for strategies
def rsi(s: pd.Series, n: int = 2) -> pd.Series:
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + g / l.replace(0, np.nan))).fillna(100.0)


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


@dataclass
class Ctx:
    rf: pd.Series
    rsi = staticmethod(rsi)
    sma = staticmethod(sma)
    load = staticmethod(load)


# ------------------------------------------------------------------ simulation
def equity_from_exposure(close: pd.Series, lev: pd.Series, rf: pd.Series, cost=COST) -> pd.Series:
    r = close.pct_change().fillna(0)
    L = lev.reindex(close.index).shift(1).fillna(0).clip(lower=0)
    ret = L * r + (1 - L) * rf - (L > 1) * LEV_EXPENSE / 252 - L.diff().abs().fillna(0) * cost
    return (1 + ret).cumprod()


def equity_from_weights(px: pd.DataFrame, w: pd.DataFrame, rf: pd.Series, cost=COST) -> pd.Series:
    rets = px.pct_change().fillna(0)
    W = w.reindex(px.index).ffill().fillna(0).shift(1).fillna(0)
    gross = W.sum(axis=1)
    ret = (W * rets).sum(axis=1) + (1 - gross) * rf - (gross > 1) * LEV_EXPENSE / 252 \
        - W.diff().abs().sum(axis=1).fillna(0) * cost
    return (1 + ret).cumprod()


def stats(eq: pd.Series, start=None, end=None) -> dict:
    e = eq
    if start is not None:
        e = e[e.index >= pd.Timestamp(start)]
    if end is not None:
        e = e[e.index < pd.Timestamp(end)]
    e = e.dropna()
    if len(e) < 60:
        return {}
    e = e / e.iloc[0]
    yrs = (e.index[-1] - e.index[0]).days / 365.25
    d = e.pct_change().dropna()
    yr = e.groupby(e.index.year).agg(["first", "last"])
    yr = yr["last"] / yr["first"] - 1
    return dict(cagr=float(e.iloc[-1] ** (1 / yrs) - 1) if e.iloc[-1] > 0 else -1.0,
                sharpe=float(d.mean() / d.std() * np.sqrt(252)) if d.std() > 0 else 0.0,
                max_dd=float((e / e.cummax() - 1).min()), worst_year=float(yr.min()),
                losing_years=int((yr < 0).sum()), years=int(len(yr)))


def bootstrap_p(excess: np.ndarray, rng) -> float:
    """One-sided p-value that mean daily excess return ≤ 0 (circular block bootstrap)."""
    n = len(excess)
    if n < BLOCK * 5:
        return 1.0
    obs = excess.mean()
    centered = excess - obs
    k = n // BLOCK + 1
    offs = np.arange(BLOCK)
    count = 0
    for _ in range(N_BOOT):
        idx = ((rng.integers(0, n, k)[:, None] + offs) % n).ravel()[:n]
        count += centered[idx].mean() >= obs
    return (count + 1) / (N_BOOT + 1)


def ruin_prob(eq: pd.Series, rng, horizon=252, threshold=-0.5) -> float:
    d = eq.pct_change().dropna().to_numpy()
    if len(d) < horizon:
        return float("nan")
    hits = 0
    for _ in range(1000):
        starts = rng.integers(0, len(d) - BLOCK, horizon // BLOCK + 1)
        path = np.concatenate([d[s:s + BLOCK] for s in starts])[:horizon]
        c = np.cumprod(1 + path)
        hits += (c / np.maximum.accumulate(c) - 1).min() <= threshold
    return hits / 1000


def _jsonable(x):
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, (np.bool_, bool)):
        return bool(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        v = float(x)
        return None if math.isnan(v) or math.isinf(v) else round(v, 4)
    return x


# ------------------------------------------------------------------ the gauntlet
@dataclass
class Result:
    passed: bool
    checks: dict
    metrics: dict
    notes: list = field(default_factory=list)

    def as_dict(self):
        """JSON-safe dict (numpy types converted) for saving to the dashboard."""
        return _jsonable({"passed": self.passed, "checks": self.checks, "metrics": self.metrics, "notes": self.notes})

    def summary(self) -> str:
        m = self.metrics
        failed = [k for k, v in self.checks.items() if not v]
        head = "PASS" if self.passed else "FAIL (" + ", ".join(failed) + ")"
        return (f"{head} | CAGR {m.get('cagr', 0)*100:.1f}% vs B&H {m.get('bh_cagr', 0)*100:.1f}% | "
                f"Sharpe {m.get('sharpe', 0):.2f} vs {m.get('bh_sharpe', 0):.2f} | "
                f"max DD {m.get('max_dd', 0)*100:.0f}% | holdout Sharpe {m.get('holdout_sharpe', 0):.2f} "
                f"vs {m.get('holdout_bh_sharpe', 0):.2f}")


def evaluate(strategy, kind: str = "exposure", ideas_tested: int = 1, symbols=None, seed: int = 7) -> Result:
    """Run the full gauntlet. kind = 'exposure' (single asset, tested on SPY first) or 'weights'
    (multi-asset; pass `symbols`)."""
    rng = np.random.default_rng(seed)
    alpha = 0.05 / (1 + math.log(max(ideas_tested, 1)))
    checks, m, notes = {}, {}, []

    if kind == "exposure":
        spy = load("SPY")
        rf = tbill(spy.index)
        ctx = Ctx(rf=rf)
        lev = strategy(spy, ctx)
        eq = equity_from_exposure(spy["Close"], lev, rf)
        bh = equity_from_exposure(spy["Close"], pd.Series(1.0, index=spy.index), rf)
        eq_cost = equity_from_exposure(spy["Close"], lev, rf, cost=COST * 4)
        L = lev.reindex(spy.index).fillna(0)
        m["exposure_avg"] = float(L.mean())
        m["trades_per_year"] = float((L.diff().abs() > 0).sum() / ((spy.index[-1] - spy.index[0]).days / 365.25))
    elif kind == "weights":
        if not symbols:
            raise ValueError("weights strategies need `symbols`")
        px = closes(symbols).dropna()
        rf = tbill(px.index)
        ctx = Ctx(rf=rf)
        w = strategy(px, ctx)
        eq = equity_from_weights(px, w, rf)
        eq_cost = equity_from_weights(px, w, rf, cost=COST * 4)
        spy = load("SPY")["Close"].reindex(px.index)
        bh = equity_from_exposure(spy, pd.Series(1.0, index=px.index), rf)
        W = w.reindex(px.index).ffill().fillna(0)
        m["exposure_avg"] = float(W.sum(axis=1).mean())
        m["trades_per_year"] = float((W.diff().abs().sum(axis=1) > 0).sum() / ((px.index[-1] - px.index[0]).days / 365.25))
    else:
        raise ValueError("kind must be 'exposure' or 'weights'")

    full, bfull = stats(eq), stats(bh)
    dev, bdev = stats(eq, DEV_START, DEV_END), stats(bh, DEV_START, DEV_END)
    hold, bhold = stats(eq, DEV_END), stats(bh, DEV_END)
    cst = stats(eq_cost)
    m.update({k: full[k] for k in full})
    m.update(bh_cagr=bfull["cagr"], bh_sharpe=bfull["sharpe"], bh_max_dd=bfull["max_dd"],
             dev_sharpe=dev.get("sharpe", 0), dev_bh_sharpe=bdev.get("sharpe", 0),
             holdout_sharpe=hold.get("sharpe", 0), holdout_bh_sharpe=bhold.get("sharpe", 0),
             holdout_cagr=hold.get("cagr", 0), holdout_bh_cagr=bhold.get("cagr", 0),
             cost4x_sharpe=cst.get("sharpe", 0), cost4x_cagr=cst.get("cagr", 0),
             data_start=str(eq.index[0].date()), data_end=str(eq.index[-1].date()))

    checks["dev"] = dev.get("sharpe", 0) > bdev.get("sharpe", 0)
    dev_mask = (eq.index >= pd.Timestamp(DEV_START)) & (eq.index < pd.Timestamp(DEV_END))
    excess = (eq.pct_change() - bh.pct_change())[dev_mask].dropna().to_numpy()
    p = bootstrap_p(excess, rng)
    m["p_value"], m["alpha_required"] = p, alpha
    checks["significance"] = p < alpha
    checks["holdout"] = hold.get("sharpe", 0) > bhold.get("sharpe", 0)
    checks["costs"] = cst.get("sharpe", 0) > bfull["sharpe"]
    rp = ruin_prob(eq, rng)
    m["ruin_prob_1y"] = rp
    checks["survival"] = (rp < 0.05) if not math.isnan(rp) else False

    if kind == "exposure":
        wins, detail = 0, {}
        for t in OTHERS:
            try:
                df = load(t)
            except FileNotFoundError:
                continue
            rft = tbill(df.index)
            ctx_t = Ctx(rf=rft)
            e = equity_from_exposure(df["Close"], strategy(df, ctx_t), rft)
            b = equity_from_exposure(df["Close"], pd.Series(1.0, index=df.index), rft)
            s, sb = stats(e), stats(b)
            detail[t] = round(s.get("sharpe", 0) - sb.get("sharpe", 0), 3)
            wins += s.get("sharpe", 0) > sb.get("sharpe", 0)
        m["other_indexes_sharpe_edge"] = detail
        checks["breadth"] = wins >= 6
        try:
            g = load("^GSPC")
            g = g[g.index < "1993-01-01"]
            rfg = tbill(g.index)
            e = equity_from_exposure(g["Close"], strategy(g, Ctx(rf=rfg)), rfg)
            b = equity_from_exposure(g["Close"], pd.Series(1.0, index=g.index), rfg)
            s, sb = stats(e), stats(b)
            m["sp1950_sharpe"], m["sp1950_bh_sharpe"] = s.get("sharpe", 0), sb.get("sharpe", 0)
            m["sp1950_cagr"], m["sp1950_bh_cagr"] = s.get("cagr", 0), sb.get("cagr", 0)
            checks["deep_history"] = s.get("sharpe", 0) >= sb.get("sharpe", 0) - 0.05
        except FileNotFoundError:
            notes.append("no ^GSPC data: deep-history check skipped (counts as fail)")
            checks["deep_history"] = False
    else:
        notes.append("multi-asset: breadth and deep-history checks not applicable")

    m = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items()}
    checks = {k: bool(v) for k, v in checks.items()}
    return Result(passed=all(checks.values()), checks=checks, metrics=m, notes=notes)


# ------------------------------------------------------------------ market health (for the dashboard)
def market_health() -> dict:
    """0–10 score from trend, breadth, volatility and momentum, plus a plain-language trend."""
    spy = load("SPY")["Close"]
    score, parts = 0.0, {}
    above200 = spy.iloc[-1] > sma(spy, 200).iloc[-1]
    above50 = spy.iloc[-1] > sma(spy, 50).iloc[-1]
    parts["SPY above 200-day"] = bool(above200)
    parts["SPY above 50-day"] = bool(above50)
    score += 3 * above200 + 1.5 * above50
    sectors = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB"]
    up = 0
    for s in sectors:
        try:
            c = load(s)["Close"]
            up += c.iloc[-1] > sma(c, 200).iloc[-1]
        except FileNotFoundError:
            pass
    parts["sectors above 200-day"] = f"{up}/9"
    score += 2.5 * up / 9
    try:
        vix = float(load("^VIX")["Close"].iloc[-1])
        parts["VIX"] = round(vix, 1)
        score += 2 if vix < 16 else 1.5 if vix < 20 else 0.75 if vix < 28 else 0
    except FileNotFoundError:
        pass
    m3 = spy.iloc[-1] / spy.iloc[-64] - 1
    parts["SPY 3-month return"] = f"{m3*100:+.1f}%"
    score += 1 if m3 > 0 else 0
    trend = ("uptrend" if above200 and above50 else "uptrend, short-term pullback" if above200
             else "downtrend, short-term bounce" if above50 else "downtrend")
    return _jsonable({"score": round(min(score, 10), 1), "trend": trend, "parts": parts,
                      "as_of": str(spy.index[-1].date())})
