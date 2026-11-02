"""Reference strategies already tested in October 2026 (see RESEARCH_HISTORY.md).
dip_boost is the current champion the agent must beat."""
import numpy as np
import pandas as pd


def buy_hold(df, ctx):
    return pd.Series(1.0, index=df.index)


def dip_boost(df, ctx):
    """Hold 1x; 2x while a dip trade is on (close > 200d avg, RSI(2) < 10, until RSI(2) > 70 or 10 days),
    only when the trailing 500-day lag-1 autocorrelation of daily returns is negative."""
    c = df["Close"]
    r = c.pct_change()
    switch = (r.rolling(500).apply(lambda x: pd.Series(x).autocorr(), raw=True) < 0).to_numpy()
    rs = ctx.rsi(c, 2).to_numpy()
    up = (c > ctx.sma(c, 200)).to_numpy()
    on, days, out = False, 0, np.ones(len(c))
    for i in range(len(c)):
        if on:
            days += 1
            if rs[i] > 70 or days >= 10:
                on = False
        elif up[i] and rs[i] < 10 and switch[i]:
            on, days = True, 0
        out[i] = 2.0 if on else 1.0
    return pd.Series(out, index=c.index)
