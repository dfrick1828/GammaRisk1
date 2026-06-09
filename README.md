# Gamma Risk Allocator — Upload by Strategy + Data Management

A Streamlit app for TradeSteward group uploads with strategy-specific analysis and upload deletion controls.

## Upload workflow

1. Choose upload type:
   - Historical backfill
   - Daily update
2. Choose strategy:
   - Weak
   - Range
   - Greenday
   - Power Hour
3. Upload TradeSteward CSV files for that selected strategy.

## Data management

The app includes controls to:

- Delete one specific upload
- Bulk delete by strategy and/or upload type
- Reset all uploaded data

Deleting an upload removes both the upload record and the associated trades.

## No manual regime selection

The app auto-detects the current gamma-risk regime from uploaded history and current data.

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
