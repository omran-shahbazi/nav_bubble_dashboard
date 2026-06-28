from pathlib import Path

import pandas as pd
import streamlit as st

from tsetmc_data import CSV_PATH, DATA_DIR, TZ, collect_gold_funds_data

CONVERSION_PATH = DATA_DIR / "gold_to_fund_conversion.csv"

st.set_page_config(
    page_title="Gold Funds NAV Bubble",
    page_icon="🟡",
    layout="wide",
)

st.markdown(
    """
    <style>
    #MainMenu, footer {visibility: hidden;}
    .block-container {
        padding-top: 3.5rem;
        padding-bottom: 2rem;
        max-width: 1100px;
        overflow: visible;
    }
    [data-testid="stMarkdownContainer"] p {
        overflow: visible;
        line-height: normal;
        margin: 0.5rem 0;
        padding: 0.25rem 0;
    }
    [data-testid="stMarkdownContainer"],
    [data-testid="column"] {
        overflow: visible;
    }
    [data-testid="stButton"] {
        padding-top: 0.35rem;
        padding-bottom: 0.35rem;
    }
    .fetch-chip {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        background: #1c2433;
        border: 1px solid #2e3a4f;
        color: #cdd6e4;
        font-size: 0.85rem;
        line-height: 1.4;
        padding: 8px 14px;
        border-radius: 999px;
        font-family: 'SF Mono', 'Menlo', monospace;
        vertical-align: middle;
    }
    .fetch-dot {
        width: 8px; height: 8px;
        border-radius: 50%;
        background: #34d399;
        box-shadow: 0 0 8px #34d399;
    }
    .page-title {
        font-size: 2.2rem;
        font-weight: 800;
        background: linear-gradient(90deg, #f7c948, #f0932b);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin: 0.2rem 0 0.1rem 0;
    }
    .page-sub {
        color: #8b97ad;
        font-size: 0.95rem;
        margin-bottom: 1.5rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(show_spinner=False)
def load_conversion() -> pd.DataFrame:
    return pd.read_csv(CONVERSION_PATH)


@st.cache_data(show_spinner=False)
def load_data(_mtime: float) -> pd.DataFrame:
    df = pd.read_csv(CSV_PATH)
    df["created_at"] = pd.to_datetime(df["created_at"])
    return df


def get_data() -> pd.DataFrame:
    if not Path(CSV_PATH).exists():
        with st.spinner("Fetching gold funds data for the first time..."):
            collect_gold_funds_data().to_csv(CSV_PATH, index=False)
    return load_data(Path(CSV_PATH).stat().st_mtime)


df = get_data()
fetch_time = df["created_at"].max().tz_convert(TZ)

top_left, top_right = st.columns([3, 1])
with top_left:
    st.markdown(
        f"""
        <span class="fetch-chip">
            <span class="fetch-dot"></span>
            Fetched&nbsp;·&nbsp;{fetch_time.strftime('%Y-%m-%d %H:%M:%S')}&nbsp;Tehran
        </span>
        """,
        unsafe_allow_html=True,
    )
with top_right:
    if st.button("🔄 Refresh", use_container_width=True):
        with st.spinner("Fetching latest data from TSETMC..."):
            collect_gold_funds_data().to_csv(CSV_PATH, index=False)
        st.cache_data.clear()
        st.rerun()

st.markdown('<div class="page-title">Gold Funds · NAV Bubble</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="page-sub">Premium (+) or discount (−) of market price relative to NAV, '
    "sorted from highest to lowest.</div>",
    unsafe_allow_html=True,
)

bubble = (
    df[["symbol", "nav_bubble", "last_price", "nav"]]
    .dropna(subset=["nav_bubble"])
    .merge(load_conversion(), on="symbol", how="left")
    .sort_values("nav_bubble", ascending=False)
    .reset_index(drop=True)
)
bubble.index = bubble.index + 1

m1, m2, m3 = st.columns(3)
with m1:
    st.metric("Highest", f"{bubble['nav_bubble'].max():+.2f}%")
    st.caption(bubble.iloc[0]["symbol"])
with m2:
    st.metric("Lowest", f"{bubble['nav_bubble'].min():+.2f}%")
    st.caption(bubble.iloc[-1]["symbol"])
with m3:
    st.metric("Average Bubble", f"{bubble['nav_bubble'].mean():+.2f}%")

st.markdown("")

def bubble_color(val: float) -> str:
    span = max(abs(bubble["nav_bubble"].min()), abs(bubble["nav_bubble"].max()), 1e-9)
    intensity = min(abs(val) / span, 1.0)
    alpha = 0.15 + 0.55 * intensity
    if val >= 0:
        return f"background-color: rgba(52, 211, 153, {alpha:.3f}); color: #000000;"
    return f"background-color: rgba(248, 113, 113, {alpha:.3f}); color: #000000;"


display = bubble.rename(
    columns={
        "symbol": "Fund",
        "nav_bubble": "NAV Bubble (%)",
        "last_price": "Last Price",
        "nav": "NAV",
    }
)[["Fund", "NAV Bubble (%)", "Last Price", "NAV", "Gold Fund Ratio"]]

styled = (
    display.style.format(
        {
            "NAV Bubble (%)": "{:+.2f}%",
            "Last Price": "{:,.0f}",
            "NAV": "{:,.0f}",
            "Gold Fund Ratio": "{:,.0f}",
        }
    )
    .map(bubble_color, subset=["NAV Bubble (%)"])
)

st.dataframe(
    styled,
    use_container_width=True,
    height=min(560, 45 + 35 * len(bubble)),
    column_config={
        "NAV Bubble (%)": st.column_config.NumberColumn(width="medium"),
        "Last Price": st.column_config.NumberColumn(width="medium", format="%.0f"),
        "NAV": st.column_config.NumberColumn(width="medium", format="%.0f"),
        "Gold Fund Ratio": st.column_config.NumberColumn(width="medium", format="%.0f"),
    },
)
