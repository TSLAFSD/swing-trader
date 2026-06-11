"""Interactive Plotly chart for HTML reports (plotly.js via CDN, touch-friendly).

Layout: 6-month candles + SMA5/20/60 + Bollinger band, BUY/SELL markers;
RSI(14), MACD, volume subplots. Dark theme matching the report template.
"""

import logging
from datetime import date

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from config import settings

logger = logging.getLogger(__name__)

_COLORS = {
    "up": "#26a69a", "down": "#ef5350", "sma5": "#ffd54f", "sma20": "#4fc3f7",
    "sma60": "#ba68c8", "bb": "rgba(120,144,156,0.35)", "vol": "#546e7a",
    "rsi": "#4fc3f7", "macd": "#4fc3f7", "macd_sig": "#ffd54f",
}


def build_chart_html(df_ind: pd.DataFrame, markers: list[dict] | None = None) -> str:
    """Render the interactive chart as an embeddable HTML div.

    Args:
        df_ind: compute_indicators() frame, full history (last 6 months drawn).
        markers: [{"date": date, "kind": "BUY"|"SELL", "price": float}].

    Returns:
        HTML div string (plotly.js loaded from CDN by the page template).
    """
    cutoff = pd.Timestamp(date.today()) - pd.DateOffset(months=settings.REPORT_CHART_MONTHS)
    df = df_ind.copy()
    df["dt"] = pd.to_datetime(df["date"])
    df = df[df["dt"] >= cutoff].reset_index(drop=True)

    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.03,
        row_heights=[0.55, 0.15, 0.15, 0.15],
        specs=[[{}], [{}], [{}], [{}]],
    )
    fig.add_trace(
        go.Candlestick(
            x=df["dt"], open=df["open"], high=df["high"], low=df["low"], close=df["close"],
            increasing_line_color=_COLORS["up"], decreasing_line_color=_COLORS["down"],
            name="가격", showlegend=False,
        ),
        row=1, col=1,
    )
    for col, label in (("sma5", "SMA5"), ("sma20", "SMA20"), ("sma60", "SMA60")):
        fig.add_trace(
            go.Scatter(x=df["dt"], y=df[col], name=label, mode="lines",
                       line=dict(width=1.2, color=_COLORS[col])),
            row=1, col=1,
        )
    for col in ("bb_upper", "bb_lower"):
        fig.add_trace(
            go.Scatter(x=df["dt"], y=df[col], mode="lines", name="볼린저",
                       line=dict(width=0.8, color=_COLORS["bb"]),
                       showlegend=(col == "bb_upper")),
            row=1, col=1,
        )
    for marker in markers or []:
        is_buy = marker["kind"] == "BUY"
        fig.add_trace(
            go.Scatter(
                x=[pd.Timestamp(marker["date"])], y=[marker["price"]],
                mode="markers+text", text=[marker["kind"]],
                textposition="bottom center" if is_buy else "top center",
                marker=dict(symbol="triangle-up" if is_buy else "triangle-down",
                            size=14, color=_COLORS["up"] if is_buy else _COLORS["down"]),
                showlegend=False,
            ),
            row=1, col=1,
        )

    fig.add_trace(
        go.Bar(x=df["dt"], y=df["volume"], name="거래량",
               marker_color=_COLORS["vol"], showlegend=False),
        row=2, col=1,
    )
    fig.add_trace(
        go.Scatter(x=df["dt"], y=df["rsi14"], name="RSI(14)", mode="lines",
                   line=dict(width=1.2, color=_COLORS["rsi"]), showlegend=False),
        row=3, col=1,
    )
    for level in (30, 70):
        fig.add_hline(y=level, line_dash="dot", line_width=0.7,
                      line_color="rgba(255,255,255,0.3)", row=3, col=1)
    fig.add_trace(
        go.Scatter(x=df["dt"], y=df["macd"], name="MACD", mode="lines",
                   line=dict(width=1.2, color=_COLORS["macd"]), showlegend=False),
        row=4, col=1,
    )
    fig.add_trace(
        go.Scatter(x=df["dt"], y=df["macd_signal"], name="시그널", mode="lines",
                   line=dict(width=1.0, color=_COLORS["macd_sig"]), showlegend=False),
        row=4, col=1,
    )
    fig.add_trace(
        go.Bar(x=df["dt"], y=df["macd_hist"], name="히스토그램",
               marker_color=_COLORS["vol"], showlegend=False),
        row=4, col=1,
    )

    fig.update_layout(
        template="plotly_dark", height=720, margin=dict(l=10, r=10, t=24, b=10),
        xaxis_rangeslider_visible=False, dragmode="pan",
        legend=dict(orientation="h", y=1.02, font=dict(size=10)),
        paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
        font=dict(family="-apple-system, sans-serif", size=11),
    )
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
    for row, title in ((2, "거래량"), (3, "RSI"), (4, "MACD")):
        fig.update_yaxes(title_text=title, title_font_size=10, row=row, col=1)

    return fig.to_html(
        include_plotlyjs="cdn", full_html=False,
        config={"scrollZoom": True, "displayModeBar": False, "responsive": True},
    )
