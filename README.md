# market-lab

Public market data + the testing engine for Filipe's Research Lab agent.

- `lab/fetch_data.py` — nightly price history and real option quotes (run by GitHub Actions)
- `lab/engine.py` — the fixed testing gauntlet every strategy goes through
- `lab/options_data.py` — helpers for the recorded option quotes
- `lab/baselines.py` — buy & hold and the current champion (dip boost)
- `AGENT.md` — the research agent's playbook
- `RESEARCH_HISTORY.md` — ideas already tested before the agent started

Contains only public market data and code. No keys, accounts or personal data.
