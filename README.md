# Gamma Risk Allocator — Upload by Strategy

A Streamlit app for TradeSteward group uploads with strategy-specific analysis.

## Upload workflow

1. Choose upload type:
   - Historical backfill
   - Daily update
2. Choose strategy:
   - Weak
   - Range
   - Greenday
   - Power Hour
3. Upload one or more TradeSteward CSV files for that selected strategy.

The app stores the strategy with every trade, so allocation and gamma-risk diagnostics remain strategy-specific.

## No manual regime selection

The app auto-detects the current regime from uploaded history and current data.

## Strategy framework

- Weak and Range = core lower-gamma-risk sleeves.
- Greenday and Power Hour = tactical sleeves for calm/compressing markets.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy

Upload these files to GitHub and deploy on Streamlit Cloud:

- `app.py`
- `requirements.txt`
- `README.md`
- `.gitignore`

Main file path:

```text
app.py
```

## Storage note

On Streamlit Cloud's free tier, local SQLite data may reset when the app restarts. For durable group storage, connect a persistent database later.
