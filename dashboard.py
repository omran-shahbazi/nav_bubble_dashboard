import html
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

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
    #MainMenu, footer, header {visibility: hidden;}
    header[data-testid="stHeader"] {display: none;}
    .block-container {
        padding-top: 1rem;
        padding-bottom: 1rem;
        max-width: 100%;
        overflow: visible;
    }
    [data-testid="stVerticalBlock"]:has(.top-bar) {
        gap: 0.25rem;
    }
    .top-bar {
        margin-bottom: 0.35rem;
    }
    [data-testid="stMarkdownContainer"] p {
        overflow: visible;
        line-height: normal;
        margin: 0;
        padding: 0;
    }
    [data-testid="stHorizontalBlock"] {
        margin-bottom: 0.35rem;
        align-items: center;
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
    iframe[title="streamlit_components_v1"] {
        border: none;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(show_spinner=False)
def load_conversion() -> pd.DataFrame:
    df = pd.read_csv(CONVERSION_PATH)
    if "Fund" in df.columns and "symbol" not in df.columns:
        df = df.rename(columns={"Fund": "symbol"})
    return df


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


def fmt_int(value: float) -> str:
    if pd.isna(value):
        return ""
    return f"{value:,.0f}"


def fmt_avg_bubble(value) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    return text if text.endswith("%") else f"{text}%"


def fmt_pct(value: float) -> str:
    if pd.isna(value):
        return ""
    return f"{value:+,.2f}%"


def parse_avg_bubble(value) -> float:
    if pd.isna(value):
        return float("nan")
    return float(str(value).strip().rstrip("%"))


def build_table_html(df: pd.DataFrame) -> str:
    rows_html = []
    for _, row in df.iterrows():
        avg_bubble = parse_avg_bubble(row["Average NAV Bubble"])
        rows_html.append(
            "<tr>"
            f"<td class='fund'>{html.escape(str(row['symbol']))}</td>"
            f"<td class='num' data-value='{row['nav_bubble']:.6f}'>{fmt_pct(row['nav_bubble'])}</td>"
            f"<td class='num' data-value='{avg_bubble:.6f}'>{fmt_avg_bubble(row['Average NAV Bubble'])}</td>"
            f"<td class='num' data-value='{row['last_price']:.0f}'>{fmt_int(row['last_price'])}</td>"
            f"<td class='num' data-value='{row['nav']:.0f}'>{fmt_int(row['nav'])}</td>"
            f"<td class='num' data-value='{row['Gold Fund Ratio']:.0f}'>{fmt_int(row['Gold Fund Ratio'])}</td>"
            f"<td class='num' data-value='{row['eq_gold_price']:.0f}'>{fmt_int(row['eq_gold_price'])}</td>"
            "</tr>"
        )

    tbody = "\n".join(rows_html)
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
* {{ box-sizing: border-box; }}
html, body {{
    margin: 0;
    padding: 0;
    background: transparent;
    overflow: hidden;
    font-family: "Source Sans Pro", sans-serif;
}}
.bubble-table {{
    width: 100%;
    table-layout: fixed;
    border-collapse: collapse;
    font-size: 0.72rem;
}}
.bubble-table th,
.bubble-table td {{
    padding: 7px 8px;
    border-bottom: 1px solid #2e3a4f;
    border-right: 1px solid #2e3a4f;
    vertical-align: middle;
}}
.bubble-table th:last-child,
.bubble-table td:last-child {{
    border-right: none;
}}
.bubble-table th {{
    color: #8b97ad;
    font-weight: 600;
    white-space: nowrap;
    user-select: none;
}}
.bubble-table th.fund-header,
.bubble-table td.fund {{
    text-align: right;
    direction: rtl;
}}
.bubble-table th.num-header,
.bubble-table td.num {{
    text-align: right;
    font-variant-numeric: tabular-nums;
    font-family: "SF Mono", "Menlo", monospace;
    white-space: nowrap;
}}
.bubble-table th.sortable {{
    cursor: pointer;
    position: relative;
    padding-left: 20px;
}}
.bubble-table th.sortable:hover {{
    color: #cdd6e4;
}}
.bubble-table th .sort-indicator {{
    position: absolute;
    left: 7px;
    top: 50%;
    transform: translateY(-50%);
    font-size: 0.65rem;
    color: #f7c948;
}}
.bubble-table tbody tr:nth-child(odd) {{
    background: #ffffff;
    color: #111827;
}}
.bubble-table tbody tr:nth-child(even) {{
    background: #3b82f6;
    color: #ffffff;
}}
.bubble-table td.fund {{
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
}}
</style>
</head>
<body>
<table class="bubble-table" id="funds-table">
<colgroup>
<col style="width:12%">
<col style="width:10%">
<col style="width:10%">
<col style="width:14%">
<col style="width:14%">
<col style="width:12%">
<col style="width:18%">
</colgroup>
<thead>
<tr>
<th class="fund-header">Fund</th>
<th class="sortable num-header" data-col="1">Bubble %<span class="sort-indicator"></span></th>
<th class="sortable num-header" data-col="2">Avg Bubble<span class="sort-indicator"></span></th>
<th class="sortable num-header" data-col="3">Last Price<span class="sort-indicator"></span></th>
<th class="sortable num-header" data-col="4">NAV<span class="sort-indicator"></span></th>
<th class="sortable num-header" data-col="5">GF Ratio<span class="sort-indicator"></span></th>
<th class="sortable num-header" data-col="6">EqGold Price<span class="sort-indicator"></span></th>
</tr>
</thead>
<tbody>
{tbody}
</tbody>
</table>
<script>
const sortState = {{}};

function sortTable(colIdx) {{
    const table = document.getElementById("funds-table");
    const tbody = table.querySelector("tbody");
    const rows = Array.from(tbody.querySelectorAll("tr"));
    const asc = sortState[colIdx] !== "asc";
    Object.keys(sortState).forEach((key) => delete sortState[key]);
    sortState[colIdx] = asc ? "asc" : "desc";

    rows.sort((a, b) => {{
        const av = parseFloat(a.children[colIdx].dataset.value);
        const bv = parseFloat(b.children[colIdx].dataset.value);
        const aNaN = Number.isNaN(av);
        const bNaN = Number.isNaN(bv);
        if (aNaN && bNaN) return 0;
        if (aNaN) return 1;
        if (bNaN) return -1;
        return asc ? av - bv : bv - av;
    }});

    rows.forEach((row) => tbody.appendChild(row));

    document.querySelectorAll("th.sortable .sort-indicator").forEach((el) => {{
        el.textContent = "";
    }});
    const active = document.querySelector(`th.sortable[data-col="${{colIdx}}"] .sort-indicator`);
    if (active) {{
        active.textContent = asc ? "▲" : "▼";
    }}
}}

document.querySelectorAll("th.sortable").forEach((header) => {{
    header.addEventListener("click", () => sortTable(Number(header.dataset.col)));
}});

sortTable(1);
</script>
</body>
</html>"""


df = get_data()
fetch_time = df["created_at"].max().tz_convert(TZ)

top_left, top_right = st.columns([3, 1])
with top_left:
    st.markdown(
        f"""
        <div class="top-bar">
            <span class="fetch-chip">
                <span class="fetch-dot"></span>
                Fetched&nbsp;·&nbsp;{fetch_time.strftime('%Y-%m-%d %H:%M:%S')}&nbsp;Tehran
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )
with top_right:
    if st.button("🔄 Refresh", use_container_width=True):
        with st.spinner("Fetching latest data from TSETMC..."):
            collect_gold_funds_data().to_csv(CSV_PATH, index=False)
        st.cache_data.clear()
        st.rerun()

bubble = (
    df[["symbol", "nav_bubble", "last_price", "nav"]]
    .dropna(subset=["nav_bubble"])
    .merge(load_conversion(), on="symbol", how="left")
    .sort_values("nav_bubble", ascending=False)
    .reset_index(drop=True)
)
bubble["eq_gold_price"] = bubble["last_price"] * bubble["Gold Fund Ratio"]

table_height = 42 + 31 * 32
components.html(build_table_html(bubble), height=table_height, scrolling=False)
