
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st


# ------------------------------------------------------------
# App setup
# ------------------------------------------------------------
st.set_page_config(page_title="Gamma Risk Allocator", layout="wide")

APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "gamma_risk_allocator.sqlite3"

DATA_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)

STRATEGIES = ["Weak", "Range", "Greenday", "Power Hour"]

st.title("Gamma Risk Allocator")
st.caption(
    "Upload TradeSteward logs by strategy. Historical backfills build the baseline; daily updates refresh the current gamma-risk signal."
)


# ------------------------------------------------------------
# Database
# ------------------------------------------------------------
def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS uploads (
                upload_id TEXT PRIMARY KEY,
                trader_alias TEXT NOT NULL,
                strategy_name TEXT NOT NULL,
                upload_type TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                stored_filename TEXT NOT NULL,
                uploaded_at TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                row_count INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                upload_id TEXT NOT NULL,
                trader_alias TEXT NOT NULL,
                strategy TEXT NOT NULL,
                upload_type TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                premium_credit REAL NOT NULL,
                net_pl REAL NOT NULL,
                actual_loss REAL NOT NULL,
                stop_threshold REAL NOT NULL,
                slippage REAL NOT NULL,
                stop_overrun INTEGER NOT NULL,
                underlying_move_pct REAL,
                abs_underlying_move_pct REAL,
                source_row_number INTEGER NOT NULL,
                UNIQUE(upload_id, source_row_number),
                FOREIGN KEY(upload_id) REFERENCES uploads(upload_id)
            )
            """
        )

        existing_upload_cols = {r[1] for r in conn.execute("PRAGMA table_info(uploads)").fetchall()}
        if "upload_type" not in existing_upload_cols:
            conn.execute("ALTER TABLE uploads ADD COLUMN upload_type TEXT NOT NULL DEFAULT 'Daily update'")

        existing_trade_cols = {r[1] for r in conn.execute("PRAGMA table_info(trades)").fetchall()}
        if "upload_type" not in existing_trade_cols:
            conn.execute("ALTER TABLE trades ADD COLUMN upload_type TEXT NOT NULL DEFAULT 'Daily update'")

        conn.commit()


init_db()


# ------------------------------------------------------------
# Column detection
# ------------------------------------------------------------
DATE_CANDIDATES = ["OpenDate", "open date", "date", "Day", "TradeDate"]
PL_CANDIDATES = ["TotalNetProfitLoss", "total net profit loss", "NetPL", "P/L", "Daily_PL"]
PREMIUM_CANDIDATES = ["TotalAverageOpen", "total average open", "Premium", "Credit"]
UNDERLYING_OPEN_CANDIDATES = ["UnderlyingOpenQuote", "Underlying Open", "SPXOpen", "Open"]
UNDERLYING_CLOSE_CANDIDATES = ["UnderlyingCloseQuote", "Underlying Close", "SPXClose", "Close"]


def clean_col(c: str) -> str:
    return str(c).strip().lower().replace("_", " ").replace("-", " ")


def find_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    cleaned = {clean_col(c): c for c in df.columns}
    for cand in candidates:
        key = clean_col(cand)
        if key in cleaned:
            return cleaned[key]
    return None


def safe_alias(name: str) -> str:
    name = str(name or "").strip()
    return name if name else "Anonymous"


def hash_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def load_trade_file(file_bytes: bytes, strategy: str) -> pd.DataFrame:
    df = pd.read_csv(pd.io.common.BytesIO(file_bytes))

    date_col = find_col(df, DATE_CANDIDATES)
    pl_col = find_col(df, PL_CANDIDATES)
    prem_col = find_col(df, PREMIUM_CANDIDATES)
    uo_col = find_col(df, UNDERLYING_OPEN_CANDIDATES)
    uc_col = find_col(df, UNDERLYING_CLOSE_CANDIDATES)

    if date_col is None:
        raise ValueError("Could not find OpenDate/date column.")
    if pl_col is None:
        raise ValueError("Could not find TotalNetProfitLoss/P&L column.")
    if prem_col is None:
        raise ValueError("Could not find TotalAverageOpen/premium column.")

    out = pd.DataFrame()
    out["strategy"] = strategy
    out["trade_date"] = pd.to_datetime(df[date_col], errors="coerce").dt.date
    out["premium_credit"] = pd.to_numeric(df[prem_col], errors="coerce") * 100
    out["net_pl"] = pd.to_numeric(df[pl_col], errors="coerce")

    out["actual_loss"] = np.where(out["net_pl"] < 0, -out["net_pl"], 0.0)
    out["stop_threshold"] = 1.5 * out["premium_credit"]
    out["slippage"] = np.maximum(0.0, out["actual_loss"] - out["stop_threshold"])
    out["stop_overrun"] = (out["slippage"] > 0).astype(int)

    if uo_col and uc_col:
        uo = pd.to_numeric(df[uo_col], errors="coerce")
        uc = pd.to_numeric(df[uc_col], errors="coerce")
        out["underlying_move_pct"] = (uc - uo) / uo * 100
        out["abs_underlying_move_pct"] = out["underlying_move_pct"].abs()
    else:
        out["underlying_move_pct"] = np.nan
        out["abs_underlying_move_pct"] = np.nan

    out["source_row_number"] = np.arange(len(out))

    return out.dropna(subset=["trade_date", "premium_credit", "net_pl"])


def save_upload(file, trader_alias: str, strategy_name: str, upload_type: str) -> Tuple[str, int]:
    file_bytes = file.getvalue()
    file_hash = hash_bytes(file_bytes)
    upload_id = hashlib.sha1(f"{file_hash}-{strategy_name}-{datetime.utcnow().isoformat()}".encode()).hexdigest()[:16]

    stored_filename = f"{upload_id}_{strategy_name.replace(' ', '_')}_{file.name}"
    stored_path = UPLOAD_DIR / stored_filename
    stored_path.write_bytes(file_bytes)

    trades = load_trade_file(file_bytes, strategy_name)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO uploads (
                upload_id, trader_alias, strategy_name, upload_type, original_filename,
                stored_filename, uploaded_at, file_hash, row_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                upload_id,
                trader_alias,
                strategy_name,
                upload_type,
                file.name,
                stored_filename,
                datetime.utcnow().isoformat(),
                file_hash,
                len(trades),
            ),
        )

        for _, r in trades.iterrows():
            conn.execute(
                """
                INSERT OR IGNORE INTO trades (
                    upload_id, trader_alias, strategy, upload_type, trade_date,
                    premium_credit, net_pl, actual_loss, stop_threshold,
                    slippage, stop_overrun, underlying_move_pct,
                    abs_underlying_move_pct, source_row_number
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    upload_id,
                    trader_alias,
                    strategy_name,
                    upload_type,
                    str(r["trade_date"]),
                    float(r["premium_credit"]),
                    float(r["net_pl"]),
                    float(r["actual_loss"]),
                    float(r["stop_threshold"]),
                    float(r["slippage"]),
                    int(r["stop_overrun"]),
                    None if pd.isna(r["underlying_move_pct"]) else float(r["underlying_move_pct"]),
                    None if pd.isna(r["abs_underlying_move_pct"]) else float(r["abs_underlying_move_pct"]),
                    int(r["source_row_number"]),
                ),
            )
        conn.commit()

    return upload_id, len(trades)


def load_all_trades() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql_query("SELECT * FROM trades", conn)
    if df.empty:
        return df
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.date
    df["stop_overrun"] = df["stop_overrun"].astype(bool)
    return df


def load_uploads() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql_query("SELECT * FROM uploads ORDER BY uploaded_at DESC", conn)
    return df


def delete_upload(upload_id: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT stored_filename FROM uploads WHERE upload_id = ?",
            (upload_id,),
        ).fetchone()

        conn.execute("DELETE FROM trades WHERE upload_id = ?", (upload_id,))
        conn.execute("DELETE FROM uploads WHERE upload_id = ?", (upload_id,))
        conn.commit()

    if row:
        stored_path = UPLOAD_DIR / row[0]
        if stored_path.exists():
            stored_path.unlink()


def delete_by_filter(strategy: Optional[str] = None, upload_type: Optional[str] = None) -> int:
    query = "SELECT upload_id, stored_filename FROM uploads WHERE 1=1"
    params = []

    if strategy:
        query += " AND strategy_name = ?"
        params.append(strategy)

    if upload_type:
        query += " AND upload_type = ?"
        params.append(upload_type)

    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(query, params).fetchall()

    for upload_id, _stored_filename in rows:
        delete_upload(upload_id)

    return len(rows)


def reset_database() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM trades")
        conn.execute("DELETE FROM uploads")
        conn.commit()

    for p in UPLOAD_DIR.glob("*"):
        if p.is_file():
            p.unlink()


# ------------------------------------------------------------
# Analytics
# ------------------------------------------------------------
def summarize_strategy(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for strategy, g in df.groupby("strategy"):
        events = g[g["slippage"] > 0]
        total_slip = g["slippage"].sum()
        rows.append({
            "Strategy": strategy,
            "Trades": len(g),
            "Net P/L": g["net_pl"].sum(),
            "Stop overruns": len(events),
            "Overrun rate": len(events) / len(g) if len(g) else 0,
            "Total slippage": total_slip,
            "Avg slippage event": events["slippage"].mean() if len(events) else 0,
            "Std dev slippage": events["slippage"].std(ddof=1) if len(events) > 1 else 0,
            "Max slippage": events["slippage"].max() if len(events) else 0,
            "Expected slippage / trade": total_slip / len(g) if len(g) else 0,
        })

    result = pd.DataFrame(rows)

    # Include missing strategies as zero rows so the dashboard always has the same structure.
    existing = set(result["Strategy"]) if not result.empty else set()
    missing_rows = []
    for strategy in STRATEGIES:
        if strategy not in existing:
            missing_rows.append({
                "Strategy": strategy,
                "Trades": 0,
                "Net P/L": 0,
                "Stop overruns": 0,
                "Overrun rate": 0,
                "Total slippage": 0,
                "Avg slippage event": 0,
                "Std dev slippage": 0,
                "Max slippage": 0,
                "Expected slippage / trade": 0,
            })
    if missing_rows:
        result = pd.concat([result, pd.DataFrame(missing_rows)], ignore_index=True)

    order = {s: i for i, s in enumerate(STRATEGIES)}
    result["sort_order"] = result["Strategy"].map(order).fillna(999)
    return result.sort_values("sort_order").drop(columns=["sort_order"])


def daily_stress(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    return (
        df.groupby("trade_date")
        .agg(
            total_slippage=("slippage", "sum"),
            net_pl=("net_pl", "sum"),
            trades=("slippage", "size"),
            stop_overruns=("stop_overrun", "sum"),
            avg_abs_spx_move=("abs_underlying_move_pct", "mean"),
            max_abs_spx_move=("abs_underlying_move_pct", "max"),
        )
        .reset_index()
        .sort_values("trade_date")
    )


def auto_regime(trades: pd.DataFrame) -> Tuple[str, str, float]:
    daily = daily_stress(trades)

    if daily.empty or len(daily) < 10:
        return "Normal", "Not enough history yet. Upload historical backfill first to build a baseline.", 50.0

    recent = daily.tail(5)
    all_range = daily["avg_abs_spx_move"].dropna()
    recent_range = recent["avg_abs_spx_move"].mean()

    if len(all_range) >= 10 and not pd.isna(recent_range):
        range_pctile = (all_range <= recent_range).mean() * 100
    else:
        range_pctile = 50.0

    rolling_slip = daily["total_slippage"].rolling(5).sum().dropna()
    recent_slip = recent["total_slippage"].sum()

    if len(rolling_slip) >= 5:
        slip_pctile = (rolling_slip <= recent_slip).mean() * 100
    else:
        slip_pctile = 50.0

    gamma_score = 0.65 * range_pctile + 0.35 * slip_pctile

    if gamma_score >= 85:
        return "Gamma stress / crisis", f"Recent realized movement/slippage is extreme. Gamma score: {gamma_score:.0f}.", gamma_score
    if gamma_score >= 70:
        return "Volatility expansion", f"Recent realized movement/slippage is elevated. Gamma score: {gamma_score:.0f}.", gamma_score
    if gamma_score <= 35:
        return "Compression / calm", f"Recent realized movement/slippage is subdued. Gamma score: {gamma_score:.0f}.", gamma_score
    return "Normal", f"Recent realized movement/slippage is normal. Gamma score: {gamma_score:.0f}.", gamma_score


def allocation_for_regime(regime: str) -> pd.DataFrame:
    maps = {
        "Compression / calm": {"Weak": 20, "Range": 30, "Greenday": 25, "Power Hour": 25},
        "Normal": {"Weak": 35, "Range": 35, "Greenday": 15, "Power Hour": 15},
        "Volatility expansion": {"Weak": 60, "Range": 30, "Greenday": 0, "Power Hour": 10},
        "Gamma stress / crisis": {"Weak": 80, "Range": 20, "Greenday": 0, "Power Hour": 0},
    }
    alloc = maps[regime]
    return pd.DataFrame({"Strategy": list(alloc.keys()), "Recommended allocation %": list(alloc.values())})


def regime_guidance(regime: str) -> str:
    if regime == "Compression / calm":
        return "Calm/compressing market. Greenday and Power Hour can be active."
    if regime == "Normal":
        return "Normal market. Weak and Range remain core; Greenday and Power Hour stay smaller."
    if regime == "Volatility expansion":
        return "Volatility expansion. Overweight Weak, keep Range moderate, and mostly disable Greenday."
    return "Gamma-stress environment. Weak/Range only; reduce total exposure if needed."


# ------------------------------------------------------------
# Sidebar upload portal — strategy-first design
# ------------------------------------------------------------
with st.sidebar:
    st.header("Upload by Strategy")

    trader_alias = safe_alias(st.text_input("Trader name or Discord handle", placeholder="@name"))

    upload_type = st.radio(
        "Upload type",
        ["Historical backfill", "Daily update"],
        index=1,
        help="Historical backfill builds the baseline. Daily update refreshes the current signal.",
    )

    selected_strategy = st.selectbox(
        "Strategy for these file(s)",
        STRATEGIES,
        index=0,
        help="All files uploaded below will be stored under this strategy.",
    )

    uploaded_files = st.file_uploader(
        f"Upload {selected_strategy} TradeSteward CSV file(s)",
        type=["csv"],
        accept_multiple_files=True,
        help="Upload one or more CSVs for the selected strategy.",
    )

    if uploaded_files and st.button(f"Process {selected_strategy} upload(s)", type="primary"):
        processed = 0
        try:
            for uploaded in uploaded_files:
                upload_id, rows = save_upload(uploaded, trader_alias, selected_strategy, upload_type)
                processed += 1
                st.success(f"{upload_type}: processed {rows} {selected_strategy} trades. Upload ID: {upload_id}")
            if processed:
                st.rerun()
        except Exception as exc:
            st.error(str(exc))

    st.divider()
    st.caption("Upload is strategy-specific. Regime detection remains automatic.")


# ------------------------------------------------------------
# Main dashboard
# ------------------------------------------------------------
trades = load_all_trades()
uploads = load_uploads()

if trades.empty:
    st.info("Start by uploading historical backfill files by strategy. After that, use daily updates to refresh the signal.")
    st.stop()

historical_trades = trades[trades["upload_type"] == "Historical backfill"].copy()
daily_update_trades = trades[trades["upload_type"] == "Daily update"].copy()

regime, note, gamma_score = auto_regime(trades)
alloc = allocation_for_regime(regime)

st.subheader("Today's Auto-Detected Gamma Regime")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Regime", regime)
c2.metric("Gamma score", f"{gamma_score:.0f}/100")
c3.metric("Historical trades", f"{len(historical_trades):,}")
c4.metric("Daily update trades", f"{len(daily_update_trades):,}")

st.info(regime_guidance(regime) + " " + note)

fig_alloc = px.bar(
    alloc,
    x="Strategy",
    y="Recommended allocation %",
    title="Recommended Strategy Allocation",
    text="Recommended allocation %",
)
fig_alloc.update_traces(texttemplate="%{text:.0f}%", textposition="outside")
fig_alloc.update_layout(yaxis_range=[0, 100])
st.plotly_chart(fig_alloc, use_container_width=True)

st.divider()
st.subheader("Upload Coverage by Strategy")

if uploads.empty:
    st.warning("No uploads yet.")
else:
    coverage = (
        uploads.groupby(["strategy_name", "upload_type"])
        .agg(files=("upload_id", "count"), rows=("row_count", "sum"))
        .reset_index()
    )
    st.dataframe(coverage, use_container_width=True)

st.divider()
st.subheader("Baseline vs Current Uploads")

bc1, bc2 = st.columns(2)

with bc1:
    st.markdown("### Historical baseline")
    if historical_trades.empty:
        st.warning("No historical backfill uploaded yet.")
    else:
        hist_summary = summarize_strategy(historical_trades)
        st.dataframe(hist_summary[["Strategy", "Trades", "Net P/L", "Overrun rate", "Expected slippage / trade"]], use_container_width=True)

with bc2:
    st.markdown("### Daily updates")
    if daily_update_trades.empty:
        st.warning("No daily update uploads yet.")
    else:
        day_summary = summarize_strategy(daily_update_trades)
        st.dataframe(day_summary[["Strategy", "Trades", "Net P/L", "Overrun rate", "Expected slippage / trade"]], use_container_width=True)

st.divider()
st.subheader("Group Strategy Diagnostics")

summary = summarize_strategy(trades)

display_summary = summary.copy()
money_cols = [
    "Net P/L",
    "Total slippage",
    "Avg slippage event",
    "Std dev slippage",
    "Max slippage",
    "Expected slippage / trade",
]
for col in money_cols:
    display_summary[col] = display_summary[col].map(lambda x: f"${x:,.2f}")
display_summary["Overrun rate"] = display_summary["Overrun rate"].map(lambda x: f"{x:.1%}")

st.dataframe(display_summary, use_container_width=True)

left, right = st.columns(2)

with left:
    fig1 = px.bar(
        summary.sort_values("Expected slippage / trade"),
        x="Strategy",
        y="Expected slippage / trade",
        title="Expected Slippage Drag Per Trade",
        text="Expected slippage / trade",
    )
    fig1.update_traces(texttemplate="$%{text:.1f}", textposition="outside")
    st.plotly_chart(fig1, use_container_width=True)

with right:
    fig2 = px.scatter(
        summary,
        x="Overrun rate",
        y="Avg slippage event",
        size="Std dev slippage",
        hover_name="Strategy",
        title="Gamma-Risk Map",
        labels={
            "Overrun rate": "Stop-overrun rate",
            "Avg slippage event": "Avg slippage event ($)",
            "Std dev slippage": "Slippage std dev",
        },
    )
    st.plotly_chart(fig2, use_container_width=True)

st.divider()
st.subheader("Daily Slippage Concentration")

daily = daily_stress(trades)
total_slip = daily["total_slippage"].sum()

top_daily = daily.sort_values("total_slippage", ascending=False).head(15).copy()
top_daily["date_label"] = pd.to_datetime(top_daily["trade_date"].astype(str)).dt.strftime("%b %d, %Y")

fig3 = px.bar(
    top_daily.sort_values("total_slippage"),
    x="total_slippage",
    y="date_label",
    orientation="h",
    title="Top Slippage Days",
    text="stop_overruns",
    labels={"total_slippage": "Total slippage beyond 150% stop ($)", "date_label": "Trade date"},
)
fig3.update_traces(texttemplate="%{text} overruns", textposition="outside")
st.plotly_chart(fig3, use_container_width=True)

m1, m2, m3 = st.columns(3)
top3_share = daily.sort_values("total_slippage", ascending=False).head(3)["total_slippage"].sum() / total_slip if total_slip else 0
top10_share = daily.sort_values("total_slippage", ascending=False).head(10)["total_slippage"].sum() / total_slip if total_slip else 0

m1.metric("Total slippage", f"${total_slip:,.0f}")
m2.metric("Top 3 days share", f"{top3_share:.1%}")
m3.metric("Top 10 days share", f"{top10_share:.1%}")

st.divider()
st.subheader("Data Management")

with st.expander("Upload history and delete controls", expanded=False):
    if uploads.empty:
        st.write("No uploads yet.")
    else:
        st.caption("Delete individual uploads if someone uploads the wrong strategy, wrong upload type, duplicate file, or corrupted export.")

        uploads_display = uploads.copy()
        uploads_display["uploaded_at"] = pd.to_datetime(uploads_display["uploaded_at"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M")

        st.dataframe(
            uploads_display[["uploaded_at", "upload_type", "trader_alias", "strategy_name", "original_filename", "row_count", "upload_id"]],
            use_container_width=True,
        )

        st.markdown("### Delete one upload")
        upload_options = [
            f"{r.uploaded_at} | {r.strategy_name} | {r.upload_type} | {r.trader_alias} | {r.original_filename} | {r.upload_id}"
            for _, r in uploads_display.iterrows()
        ]

        selected_upload_label = st.selectbox("Select upload to delete", upload_options)
        selected_upload_id = selected_upload_label.split("|")[-1].strip()

        confirm_single = st.checkbox("Confirm delete selected upload")
        if st.button("Delete selected upload", type="secondary", disabled=not confirm_single):
            delete_upload(selected_upload_id)
            st.success("Selected upload deleted.")
            st.rerun()

        st.markdown("---")
        st.markdown("### Bulk delete")

        c1, c2 = st.columns(2)
        with c1:
            bulk_strategy = st.selectbox("Strategy filter", ["All strategies"] + STRATEGIES)
        with c2:
            bulk_type = st.selectbox("Upload type filter", ["All upload types", "Historical backfill", "Daily update"])

        strategy_filter = None if bulk_strategy == "All strategies" else bulk_strategy
        type_filter = None if bulk_type == "All upload types" else bulk_type

        confirm_bulk_text = st.text_input("Type DELETE to confirm bulk delete")
        if st.button("Bulk delete matching uploads", type="secondary", disabled=confirm_bulk_text != "DELETE"):
            deleted = delete_by_filter(strategy_filter, type_filter)
            st.success(f"Deleted {deleted} matching upload(s).")
            st.rerun()

        st.markdown("---")
        st.markdown("### Reset all data")
        st.warning("This removes every upload, every trade, and every stored CSV.")
        confirm_reset_text = st.text_input("Type RESET ALL to confirm full reset")
        if st.button("Reset database", type="secondary", disabled=confirm_reset_text != "RESET ALL"):
            reset_database()
            st.success("Database reset.")
            st.rerun()

with st.expander("Download normalized group diagnostics"):
    csv = trades.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download normalized CSV",
        data=csv,
        file_name="gamma_risk_group_diagnostics.csv",
        mime="text/csv",
    )
