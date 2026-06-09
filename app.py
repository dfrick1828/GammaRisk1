
from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st


# ------------------------------------------------------------
# App configuration
# ------------------------------------------------------------
st.set_page_config(
    page_title="Gamma Risk Allocator",
    layout="wide",
)

st.title("Gamma Risk Allocator")
st.caption(
    "A TradeSteward companion model for deciding when to deploy Weak, Range, Greenday, and Power Hour based on realized gamma-risk conditions."
)


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
DATE_CANDIDATES = ["OpenDate", "open date", "date", "Day", "TradeDate"]
TIME_CANDIDATES = ["OpenTime", "open time", "time"]
PL_CANDIDATES = ["TotalNetProfitLoss", "total net profit loss", "NetPL", "P/L", "Daily_PL"]
PREMIUM_CANDIDATES = ["TotalAverageOpen", "total average open", "Premium", "Credit"]
UNDERLYING_OPEN_CANDIDATES = ["UnderlyingOpenQuote", "Underlying Open", "SPXOpen", "Open"]
UNDERLYING_CLOSE_CANDIDATES = ["UnderlyingCloseQuote", "Underlying Close", "SPXClose", "Close"]
VIX_OPEN_CANDIDATES = ["VIXOpenQuote", "VIX Open", "VIXOpen"]
VIX_CLOSE_CANDIDATES = ["VIXCloseQuote", "VIX Close", "VIXClose"]


def clean_col(c: str) -> str:
    return str(c).strip().lower().replace("_", " ").replace("-", " ")


def find_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    cleaned = {clean_col(c): c for c in df.columns}
    for cand in candidates:
        key = clean_col(cand)
        if key in cleaned:
            return cleaned[key]
    return None


def normalize_strategy_name(name: str) -> str:
    s = str(name or "").strip().lower()
    if "weak" in s:
        return "Weak"
    if "range" in s:
        return "Range"
    if "green" in s:
        return "Greenday"
    if "power" in s:
        return "Power Hour"
    return str(name or "Unknown").strip() or "Unknown"


def infer_strategy_from_filename(filename: str) -> str:
    f = filename.lower()
    if "weak" in f:
        return "Weak"
    if "range" in f:
        return "Range"
    if "green" in f:
        return "Greenday"
    if "power" in f:
        return "Power Hour"
    return "Unspecified"


def load_trade_file(uploaded_file, fallback_strategy: str) -> pd.DataFrame:
    df = pd.read_csv(uploaded_file)

    date_col = find_col(df, DATE_CANDIDATES)
    pl_col = find_col(df, PL_CANDIDATES)
    prem_col = find_col(df, PREMIUM_CANDIDATES)
    uo_col = find_col(df, UNDERLYING_OPEN_CANDIDATES)
    uc_col = find_col(df, UNDERLYING_CLOSE_CANDIDATES)
    vo_col = find_col(df, VIX_OPEN_CANDIDATES)
    vc_col = find_col(df, VIX_CLOSE_CANDIDATES)

    if date_col is None:
        raise ValueError(f"{uploaded_file.name}: could not find OpenDate/date column.")
    if pl_col is None:
        raise ValueError(f"{uploaded_file.name}: could not find TotalNetProfitLoss/P&L column.")
    if prem_col is None:
        raise ValueError(f"{uploaded_file.name}: could not find TotalAverageOpen/premium column.")

    out = pd.DataFrame()
    out["strategy"] = fallback_strategy

    if "Strategy" in df.columns:
        detected = df["Strategy"].dropna().astype(str)
        if len(detected):
            # Keep fallback if the platform strategy names are inconsistent.
            pass

    out["trade_date"] = pd.to_datetime(df[date_col], errors="coerce").dt.date
    out["premium_credit"] = pd.to_numeric(df[prem_col], errors="coerce") * 100
    out["net_pl"] = pd.to_numeric(df[pl_col], errors="coerce")

    out["actual_loss"] = np.where(out["net_pl"] < 0, -out["net_pl"], 0.0)
    out["stop_threshold"] = 1.5 * out["premium_credit"]
    out["slippage"] = np.maximum(0.0, out["actual_loss"] - out["stop_threshold"])
    out["stop_overrun"] = out["slippage"] > 0

    if uo_col and uc_col:
        out["underlying_open"] = pd.to_numeric(df[uo_col], errors="coerce")
        out["underlying_close"] = pd.to_numeric(df[uc_col], errors="coerce")
        out["underlying_move_pct"] = (out["underlying_close"] - out["underlying_open"]) / out["underlying_open"] * 100
        out["abs_underlying_move_pct"] = out["underlying_move_pct"].abs()
    else:
        out["underlying_open"] = np.nan
        out["underlying_close"] = np.nan
        out["underlying_move_pct"] = np.nan
        out["abs_underlying_move_pct"] = np.nan

    if vo_col and vc_col:
        out["vix_open"] = pd.to_numeric(df[vo_col], errors="coerce")
        out["vix_close"] = pd.to_numeric(df[vc_col], errors="coerce")
        out["vix_change_pct"] = (out["vix_close"] - out["vix_open"]) / out["vix_open"] * 100
    else:
        out["vix_open"] = np.nan
        out["vix_close"] = np.nan
        out["vix_change_pct"] = np.nan

    return out.dropna(subset=["trade_date", "premium_credit", "net_pl"])


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
            "Median slippage event": events["slippage"].median() if len(events) else 0,
            "Std dev slippage": events["slippage"].std(ddof=1) if len(events) > 1 else 0,
            "Max slippage": events["slippage"].max() if len(events) else 0,
            "Expected slippage / trade": total_slip / len(g) if len(g) else 0,
        })
    return pd.DataFrame(rows)


def daily_stress(df: pd.DataFrame) -> pd.DataFrame:
    daily = df.groupby("trade_date").agg(
        total_slippage=("slippage", "sum"),
        net_pl=("net_pl", "sum"),
        trades=("slippage", "size"),
        stop_overruns=("stop_overrun", "sum"),
        avg_abs_spx_move=("abs_underlying_move_pct", "mean"),
        max_abs_spx_move=("abs_underlying_move_pct", "max"),
        avg_vix_change=("vix_change_pct", "mean"),
        avg_vix_open=("vix_open", "mean"),
    ).reset_index()

    if daily["avg_abs_spx_move"].notna().sum() >= 10:
        daily["range_rank"] = daily["avg_abs_spx_move"].rank(pct=True)
    else:
        daily["range_rank"] = np.nan

    if daily["total_slippage"].notna().sum() >= 10:
        daily["slippage_rank"] = daily["total_slippage"].rank(pct=True)
    else:
        daily["slippage_rank"] = np.nan

    return daily.sort_values("trade_date")


def classify_regime(
    expected_spx_intraday_move: float,
    recent_range_rank: float,
    overnight_gap_pct: float,
    trend_persistence: float,
) -> Tuple[str, str]:
    """
    expected_spx_intraday_move: user-entered expected absolute intraday SPX move in percent.
    recent_range_rank: recent realized range percentile, 0-100.
    overnight_gap_pct: absolute overnight gap in percent.
    trend_persistence: 0-100 estimate of one-way/trending price action risk.
    """
    score = 0

    if expected_spx_intraday_move >= 1.25:
        score += 3
    elif expected_spx_intraday_move >= 0.85:
        score += 2
    elif expected_spx_intraday_move >= 0.55:
        score += 1

    if recent_range_rank >= 85:
        score += 3
    elif recent_range_rank >= 70:
        score += 2
    elif recent_range_rank >= 55:
        score += 1

    if abs(overnight_gap_pct) >= 0.85:
        score += 2
    elif abs(overnight_gap_pct) >= 0.45:
        score += 1

    if trend_persistence >= 75:
        score += 2
    elif trend_persistence >= 55:
        score += 1

    if score <= 2:
        return "Compression / calm", "Low gamma-stress risk"
    if score <= 5:
        return "Normal", "Moderate gamma-stress risk"
    if score <= 8:
        return "Volatility expansion", "Elevated gamma-stress risk"
    return "Gamma stress / crisis", "High gamma-stress risk"


def allocation_for_regime(regime: str) -> pd.DataFrame:
    maps = {
        "Compression / calm": {
            "Weak": 20,
            "Range": 30,
            "Greenday": 25,
            "Power Hour": 25,
        },
        "Normal": {
            "Weak": 35,
            "Range": 35,
            "Greenday": 15,
            "Power Hour": 15,
        },
        "Volatility expansion": {
            "Weak": 60,
            "Range": 30,
            "Greenday": 0,
            "Power Hour": 10,
        },
        "Gamma stress / crisis": {
            "Weak": 80,
            "Range": 20,
            "Greenday": 0,
            "Power Hour": 0,
        },
    }
    alloc = maps[regime]
    return pd.DataFrame({
        "Strategy": list(alloc.keys()),
        "Recommended allocation %": list(alloc.values()),
    })


# ------------------------------------------------------------
# Sidebar controls
# ------------------------------------------------------------
with st.sidebar:
    st.header("Upload TradeSteward logs")
    st.write("Upload one CSV per strategy. File names can include Weak, Range, Greenday, or Power Hour.")

    uploaded_files = st.file_uploader(
        "TradeSteward CSV files",
        type=["csv"],
        accept_multiple_files=True,
    )

    st.divider()
    st.header("Daily regime inputs")
    st.caption("Use realized SPX movement / gamma stress, not VIX, as the primary filter.")

    expected_spx_intraday_move = st.slider(
        "Expected absolute SPX intraday move (%)",
        min_value=0.0,
        max_value=3.0,
        value=0.65,
        step=0.05,
    )

    recent_range_rank = st.slider(
        "Recent intraday range percentile",
        min_value=0,
        max_value=100,
        value=50,
        step=1,
        help="Example: 80 means recent realized intraday range is in the top 20% of observed days.",
    )

    overnight_gap_pct = st.slider(
        "Absolute overnight SPX gap (%)",
        min_value=0.0,
        max_value=3.0,
        value=0.20,
        step=0.05,
    )

    trend_persistence = st.slider(
        "Trend persistence risk",
        min_value=0,
        max_value=100,
        value=40,
        step=1,
        help="Higher means more risk of one-way intraday movement instead of chop/mean reversion.",
    )


# ------------------------------------------------------------
# Daily signal
# ------------------------------------------------------------
regime, risk_label = classify_regime(
    expected_spx_intraday_move,
    recent_range_rank,
    overnight_gap_pct,
    trend_persistence,
)

alloc = allocation_for_regime(regime)

st.subheader("Today's Gamma-Risk Signal")

c1, c2, c3 = st.columns(3)
c1.metric("Regime", regime)
c2.metric("Risk label", risk_label)
c3.metric("Primary rule", "Favor Weak/Range" if regime in ["Volatility expansion", "Gamma stress / crisis"] else "Tactical sleeves allowed")

fig_alloc = px.bar(
    alloc,
    x="Strategy",
    y="Recommended allocation %",
    title="Recommended Strategy Allocation",
    text="Recommended allocation %",
)
fig_alloc.update_traces(texttemplate="%{text:.0f}%", textposition="outside")
fig_alloc.update_layout(yaxis_range=[0, max(100, alloc["Recommended allocation %"].max() + 10)])
st.plotly_chart(fig_alloc, use_container_width=True)

st.info(
    "Interpretation: Weak and Range are treated as core lower-gamma-risk sleeves. "
    "Greenday and Power Hour are tactical sleeves for calmer, compressing regimes."
)


# ------------------------------------------------------------
# Uploaded data analysis
# ------------------------------------------------------------
if uploaded_files:
    frames = []
    errors = []

    for f in uploaded_files:
        fallback = infer_strategy_from_filename(f.name)
        # If the file name is generic, allow the user to map later by Strategy column; fallback remains.
        try:
            frames.append(load_trade_file(f, fallback))
        except Exception as exc:
            errors.append(str(exc))

    if errors:
        st.error("Some files could not be processed:")
        for e in errors:
            st.write(e)

    if frames:
        trades = pd.concat(frames, ignore_index=True)
        trades = trades[trades["strategy"] != "Unspecified"].copy()

        st.divider()
        st.subheader("Historical Gamma-Risk Diagnostics")

        summary = summarize_strategy(trades)

        if not summary.empty:
            display_summary = summary.copy()
            money_cols = [
                "Net P/L",
                "Total slippage",
                "Avg slippage event",
                "Median slippage event",
                "Std dev slippage",
                "Max slippage",
                "Expected slippage / trade",
            ]
            for col in money_cols:
                display_summary[col] = display_summary[col].map(lambda x: f"${x:,.2f}")
            display_summary["Overrun rate"] = display_summary["Overrun rate"].map(lambda x: f"{x:.1%}")
            st.dataframe(display_summary, use_container_width=True)

            fig = px.bar(
                summary.sort_values("Expected slippage / trade"),
                x="Strategy",
                y="Expected slippage / trade",
                title="Expected Slippage Drag Per Trade",
                text="Expected slippage / trade",
            )
            fig.update_traces(texttemplate="$%{text:.1f}", textposition="outside")
            st.plotly_chart(fig, use_container_width=True)

            fig2 = px.scatter(
                summary,
                x="Overrun rate",
                y="Avg slippage event",
                size="Std dev slippage",
                hover_name="Strategy",
                title="Gamma-Risk Map: Frequency vs Severity",
                labels={
                    "Overrun rate": "Stop-overrun rate",
                    "Avg slippage event": "Average slippage event ($)",
                    "Std dev slippage": "Slippage standard deviation",
                },
            )
            st.plotly_chart(fig2, use_container_width=True)

        daily = daily_stress(trades)
        if not daily.empty:
            st.subheader("Slippage Concentration by Date")
            top_daily = daily.sort_values("total_slippage", ascending=False).head(20).copy()
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

            total_slip = daily["total_slippage"].sum()
            top3_share = daily.sort_values("total_slippage", ascending=False).head(3)["total_slippage"].sum() / total_slip if total_slip else 0
            top10_share = daily.sort_values("total_slippage", ascending=False).head(10)["total_slippage"].sum() / total_slip if total_slip else 0

            d1, d2, d3 = st.columns(3)
            d1.metric("Total historical slippage", f"${total_slip:,.0f}")
            d2.metric("Top 3 days share", f"{top3_share:.1%}")
            d3.metric("Top 10 days share", f"{top10_share:.1%}")

        with st.expander("Download normalized trade diagnostics"):
            csv = trades.to_csv(index=False).encode("utf-8")
            st.download_button(
                "Download normalized CSV",
                data=csv,
                file_name="gamma_risk_trade_diagnostics.csv",
                mime="text/csv",
            )

else:
    st.divider()
    st.subheader("How to use this")
    st.markdown(
        """
        1. Upload your TradeSteward CSV exports for Weak, Range, Greenday, and Power Hour.
        2. The app calculates stop-overrun slippage using: `max(0, actual loss - 1.5 × premium collected)`.
        3. Use the daily sliders to classify the current market regime.
        4. Use the allocation chart to decide which bots should be active, reduced, or off.

        Suggested rule of thumb:

        - **Compression / calm:** allow Greenday and Power Hour.
        - **Normal:** core Weak/Range, smaller Greenday/Power Hour.
        - **Volatility expansion:** overweight Weak, reduce Range, mostly disable Greenday and Power Hour.
        - **Gamma stress / crisis:** Weak/Range only, with reduced overall exposure.
        """
    )
