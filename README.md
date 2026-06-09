# Gamma Risk Allocator — Group Upload Portal

A Streamlit app for daily TradeSteward uploads from a trading group.

## Purpose

The app removes manual regime selection. Users upload current TradeSteward CSVs daily, and the app auto-detects the current gamma-risk regime from accumulated realized movement and stop-overrun/slippage behavior.

## Workflow

1. Each trader uploads a TradeSteward CSV.
2. The app stores uploads in a local SQLite database.
3. The app calculates:
   - premium collected
   - 150% stop threshold
   - stop-overrun slippage
   - strategy-level gamma-risk diagnostics
   - daily slippage concentration
4. The app auto-detects the regime:
   - Compression / calm
   - Normal
   - Volatility expansion
   - Gamma stress / crisis
5. The app recommends allocation across:
   - Weak
   - Range
   - Greenday
   - Power Hour

## Core thesis

The portfolio's dominant risk factor is gamma risk, not VIX. Weak and Range are treated as core lower-gamma-risk sleeves. Greenday and Power Hour are tactical sleeves for calm/compressing markets.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy on Streamlit Cloud

Upload these files to GitHub:

- `app.py`
- `requirements.txt`
- `README.md`
- `.gitignore`

Then deploy with main file path:

```text
app.py
```

## Data note

On Streamlit Cloud's free tier, local SQLite storage may reset when the app restarts. For durable group storage, connect the app to a persistent database or cloud storage later.
