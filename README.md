# Gamma Risk Allocator

A Streamlit companion app for TradeSteward strategy management.

The app helps decide when to deploy **Weak**, **Range**, **Greenday**, and **Power Hour** based on realized gamma-risk conditions rather than VIX.

## What it does

- Upload TradeSteward CSV exports.
- Calculates stop-overrun slippage using:

```text
Slippage = max(0, actual loss - 1.5 × premium collected)
```

- Summarizes strategy-level gamma risk:
  - stop-overrun rate
  - average slippage event
  - standard deviation of slippage
  - expected slippage drag per trade
  - maximum slippage
- Classifies the current market regime:
  - Compression / calm
  - Normal
  - Volatility expansion
  - Gamma stress / crisis
- Produces recommended allocation across:
  - Weak
  - Range
  - Greenday
  - Power Hour

## Core thesis

The portfolio risk is driven less by traditional VIX and more by realized intraday gamma stress.

Weak and Range are treated as core lower-gamma-risk strategies. Greenday and Power Hour are treated as tactical strategies for calmer/compressing regimes.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy on Streamlit Cloud

1. Create a GitHub repository.
2. Upload these files:
   - `app.py`
   - `requirements.txt`
   - `README.md`
3. Go to Streamlit Cloud.
4. Select the repo.
5. Set the main file path to:

```text
app.py
```

6. Deploy.

## Notes

This is not financial advice. The gamma-risk score and allocation framework are research tools based on historical TradeSteward logs and user-defined assumptions.
