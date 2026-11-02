# Research history (October 2026, before the agent)

Tested by hand with the same style of checks. Treat these as already-tested ideas.

| Idea | Result |
|---|---|
| RSI(2) dip-buying on 30 large caps (cash otherwise) | Real edge per trade, but mostly in cash → trailed SPY. Single-stock results came from survivorship (failed on unseen stocks). |
| Weekly SPY put credit spreads ($1 wide) | Failed: edge only under one IV assumption; costs killed it. |
| Monthly SPY put spreads (16Δ, $5 wide) | ~0.4%/yr at 2% risk. Failed. |
| Monthly SPY iron condors (16Δ, $10 wings) | Break-even to negative; failed under 2× costs. |
| ITM calls on index dips | Looked strong until a modelling flaw was fixed (IV rising while held); corrected ~6.7%/yr < SPY. |
| Same signal via 3x leveraged ETFs (cash otherwise) | 2–5%/yr. Failed. |
| FlatFly 0DTE SPX iron butterfly | Claimed edge ≈ $0.30/fly ≈ realistic slippage; SPX does not revert to prior close (39–46%). Not adopted. |
| Pre-earnings straddles | Academic support (Gao, Xing & Zhang 2018); needs real per-stock option data. Untested. |
| Trend 200-day, MA cross, Donchian breakout, Bollinger range, grid, vol targeting, turn of month, 12m time-series momentum | All failed the full gauntlet (trend-type: lower drawdown, failed breadth). |
| Sector rotation, index rotation, dual momentum | Did not beat SPY risk-adjusted. |
| A+ confluence sizing (breadth, VIX spike, turn of month) | No reliable improvement over uniform sizing. |
| **Dip boost + autocorrelation switch** | **Champion.** SPY 1993→now 14.5%/yr vs 10.8%; ties B&H 1950–92; 2x SSO only during dips. |

Lessons: modelled option prices mislead; survivorship inflates single-stock tests; extra rules add
overfitting; the dip-bounce effect only exists since ~1990 (positive autocorrelation before).
