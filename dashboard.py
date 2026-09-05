import json
import html
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from tsetmc_data import (
    CSV_PATH,
    DATA_DIR,
    HISTORY_CSV_PATH,
    TZ,
    append_daily_snapshot,
    collect_gold_funds_data,
    normalize_snapshot,
    symbols,
    write_csv_atomic,
)

CONVERSION_PATH = DATA_DIR / "gold_to_fund_conversion.csv"
REFRESH_STATUS_PATH = DATA_DIR / "refresh_status.json"
LIVE_TTL_SECONDS = 180
FLASH_FIELDS = (
    "nav_bubble",
    "avg_bubble_50",
    "bubble_deviation",
    "last_price",
    "nav",
    "eq_gold_price",
)

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
    }
    .fetch-dot.live {
        background: #34d399;
        box-shadow: 0 0 8px #34d399;
    }
    .fetch-dot.cached {
        background: #fbbf24;
        box-shadow: 0 0 8px #fbbf24;
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
def load_data(mtime: float) -> pd.DataFrame:
    return normalize_snapshot(pd.read_csv(CSV_PATH))


@st.cache_data(show_spinner=False)
def load_history(mtime: float) -> pd.DataFrame:
    try:
        df = pd.read_csv(HISTORY_CSV_PATH)
    except (UnicodeDecodeError, pd.errors.ParserError):
        # A legacy/interrupted writer may have left a malformed row. Keep the
        # dashboard usable and let the next atomic refresh replace the file.
        df = pd.read_csv(
            HISTORY_CSV_PATH,
            encoding="utf-8",
            encoding_errors="replace",
            engine="python",
            on_bad_lines="skip",
        )
    return normalize_snapshot(df)


def get_data() -> pd.DataFrame:
    if Path(CSV_PATH).exists() and Path(CSV_PATH).stat().st_size > 0:
        current = load_data(Path(CSV_PATH).stat().st_mtime)
        if not current.empty:
            return current

    # A historical snapshot keeps the dashboard usable while TSETMC is unavailable.
    if HISTORY_CSV_PATH.exists():
        history = load_history(HISTORY_CSV_PATH.stat().st_mtime)
        return (
            history.sort_values(["symbol", "market_date", "observed_at"])
            .groupby("symbol", as_index=False)
            .tail(1)
            .reset_index(drop=True)
        )
    return pd.DataFrame()


def get_history(seed_data: pd.DataFrame) -> pd.DataFrame:
    if not HISTORY_CSV_PATH.exists():
        append_daily_snapshot(seed_data)
    return load_history(HISTORY_CSV_PATH.stat().st_mtime)


@st.cache_resource(show_spinner=False)
def get_refresh_executor() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=1, thread_name_prefix="tsetmc-refresh")


def is_complete_snapshot(data: pd.DataFrame) -> bool:
    return (
        len(data) == len(symbols)
        and data["symbol"].nunique() == len(symbols)
        and data["market_date"].notna().all()
    )


def read_refresh_status() -> dict:
    if not REFRESH_STATUS_PATH.exists():
        return {"mode": "cached"}
    try:
        return json.loads(REFRESH_STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"mode": "cached"}


def write_refresh_status(**status) -> None:
    REFRESH_STATUS_PATH.write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def collect_finished_refresh() -> None:
    future = st.session_state.get("refresh_future")
    if future is None or not future.done():
        return

    del st.session_state["refresh_future"]
    now = datetime.now(TZ)
    previous = read_refresh_status()
    try:
        refreshed_data = future.result()
    except Exception as error:
        write_refresh_status(
            mode="cached",
            last_success_at=previous.get("last_success_at"),
            last_attempt_at=now.isoformat(),
            error=str(error),
        )
        return

    if is_complete_snapshot(refreshed_data):
        write_csv_atomic(refreshed_data, CSV_PATH)
        append_daily_snapshot(refreshed_data)
        write_refresh_status(
            mode="live",
            last_success_at=now.isoformat(),
            last_attempt_at=now.isoformat(),
            funds=len(refreshed_data),
        )
    else:
        write_refresh_status(
            mode="cached",
            last_success_at=previous.get("last_success_at"),
            last_attempt_at=now.isoformat(),
            error="TSETMC did not return a complete 31-fund snapshot",
        )


def start_background_refresh() -> bool:
    future = st.session_state.get("refresh_future")
    if future is not None and not future.done():
        return False

    st.session_state["refresh_future"] = get_refresh_executor().submit(collect_gold_funds_data)
    return True


def run_manual_refresh() -> None:
    start_background_refresh()
    future = st.session_state.get("refresh_future")
    if future is not None:
        with st.spinner("Fetching latest data from TSETMC..."):
            wait([future])
        collect_finished_refresh()
    st.rerun()


def refresh_badge(fetch_time: pd.Timestamp) -> tuple[str, str, str]:
    snapshot_time = fetch_time.strftime('%Y-%m-%d %H:%M:%S')
    if st.session_state.get("refresh_future") is not None:
        return "cached", "Refreshing...", f"نمایش آخرین snapshot معتبر · {snapshot_time}"

    status = read_refresh_status()
    last_success = status.get("last_success_at")
    if status.get("mode") == "live" and last_success:
        try:
            age = datetime.now(TZ) - datetime.fromisoformat(last_success)
            if age <= timedelta(seconds=LIVE_TTL_SECONDS):
                return "live", "Live · TSETMC", f"۳۱ صندوق با موفقیت دریافت شد · {snapshot_time}"
        except ValueError:
            pass

    return "cached", "Cached", f"آخرین snapshot: {snapshot_time}"


def fmt_int(value: float) -> str:
    if pd.isna(value):
        return ""
    return f"{value:,.0f}"


def fmt_rolling_avg(value: float) -> str:
    if pd.isna(value):
        return "—"
    return f"{value:.2f}%"


def fmt_pct(value: float) -> str:
    if pd.isna(value):
        return "—"
    return f"{value:+,.2f}%"


def sparkline_svg(values) -> str:
    points = []
    dates = []
    for item in values:
        if isinstance(item, dict):
            value = item.get("value")
            dates.append(str(item.get("date", "")))
        else:
            value = item
        if value is not None and not pd.isna(value):
            points.append(float(value))
    if len(points) < 2:
        return "<span class='sparkline-empty'>—</span>"

    width, height, padding = 100, 30, 2
    extent = max(abs(min(points)), abs(max(points)), 0.1)
    zero_y = height / 2
    coordinates = " ".join(
        f"{padding + index * (width - 2 * padding) / (len(points) - 1):.1f},"
        f"{zero_y - value / extent * (height / 2 - padding):.1f}"
        for index, value in enumerate(points)
    )
    stroke = "#b91c1c" if points[-1] > 0 else "#15803d" if points[-1] < 0 else "#475569"
    date_range = f" · {dates[0]} to {dates[-1]}" if len(dates) >= 2 and dates[0] else ""
    title = html.escape(
        f"{len(points)} observations · Last {points[-1]:+.2f}% · "
        f"Range {min(points):+.2f}% to {max(points):+.2f}{date_range}"
    )
    return (
        f"<svg class='sparkline' viewBox='0 0 {width} {height}' role='img'>"
        f"<title>{title}</title>"
        f"<line x1='0' y1='{zero_y}' x2='{width}' y2='{zero_y}' class='sparkline-zero'/>"
        f"<polyline points='{coordinates}' fill='none' stroke='{stroke}' stroke-width='1.8' "
        "stroke-linecap='round' stroke-linejoin='round'/></svg>"
    )


def changed_cell_classes(df: pd.DataFrame) -> dict[tuple[str, str], str]:
    """Return short-lived visual directions against the prior valid snapshot."""
    current = {
        str(row["symbol"]): {
            field: (float(row[field]) if pd.notna(row[field]) else None)
            for field in FLASH_FIELDS
        }
        for _, row in df.iterrows()
    }
    previous = st.session_state.get("previous_table_cells")
    st.session_state["previous_table_cells"] = current
    if previous is None:
        return {}

    changed = {}
    for symbol, fields in current.items():
        for field, value in fields.items():
            old_value = previous.get(symbol, {}).get(field)
            if value is None or old_value is None or value == old_value:
                continue
            changed[(symbol, field)] = "cell-flash-up" if value > old_value else "cell-flash-down"
    return changed


def build_download_csv(df: pd.DataFrame) -> bytes:
    download_df = df[
        [
            "symbol",
            "fund_name",
            "nav_bubble",
            "avg_bubble_50",
            "bubble_deviation",
            "last_price",
            "nav",
            "Gold Fund Ratio",
            "eq_gold_price",
        ]
    ].rename(
        columns={
            "symbol": "Fund",
            "fund_name": "Fund Name",
            "nav_bubble": "Bubble %",
            "avg_bubble_50": "Avg Bubble(50D)",
            "bubble_deviation": "Bubble Deviation(50D)",
            "last_price": "Last Price",
            "nav": "NAV",
            "Gold Fund Ratio": "GF Ratio",
            "eq_gold_price": "EqGold Price",
        }
    )
    return download_df.to_csv(index=False).encode("utf-8-sig")


def build_table_html(
    df: pd.DataFrame,
    cell_flashes: dict[tuple[str, str], str],
) -> str:
    rows_html = []
    for _, row in df.iterrows():
        symbol_key = str(row["symbol"])
        symbol = html.escape(symbol_key, quote=True)
        fund_name = html.escape(str(row.get("fund_name") or row["symbol"]), quote=True)
        trend_data = row.get("bubble_trend", [])
        trend = sparkline_svg(trend_data)
        trend_payload = html.escape(json.dumps(trend_data, ensure_ascii=False), quote=True)
        cell_class = lambda field, base="num": f"{base} {cell_flashes.get((symbol_key, field), '')}".strip()
        rows_html.append(
            f"<tr data-symbol='{symbol}' data-pinned='false'>"
            f"<td class='fund' title='{fund_name}' aria-label='{fund_name}'>"
            f"<span class='fund-symbol'><button class='pin-toggle' type='button' title='Pin this fund' aria-label='Pin {symbol}'>☆</button>{symbol}</span>"
            f"<span class='fund-name'>{fund_name}</span>"
            "</td>"
            f"<td class='sparkline-cell' data-trend='{trend_payload}' title='Click to enlarge trend' role='button' tabindex='0' aria-label='Enlarge Bubble Trend for {symbol}'>{trend}</td>"
            f"<td class='{cell_class('nav_bubble')}' data-value='{row['nav_bubble']:.6f}'>{fmt_pct(row['nav_bubble'])}</td>"
            f"<td class='{cell_class('avg_bubble_50')}' data-value='{row['avg_bubble_50']:.6f}'>{fmt_rolling_avg(row['avg_bubble_50'])}</td>"
            f"<td class='{cell_class('bubble_deviation')}' data-value='{row['bubble_deviation']:.6f}'>{fmt_pct(row['bubble_deviation'])}</td>"
            f"<td class='{cell_class('last_price')}' data-value='{row['last_price']:.0f}'>{fmt_int(row['last_price'])}</td>"
            f"<td class='{cell_class('nav')}' data-value='{row['nav']:.0f}'>{fmt_int(row['nav'])}</td>"
            f"<td class='num' data-value='{row['Gold Fund Ratio']:.0f}'>{fmt_int(row['Gold Fund Ratio'])}</td>"
            f"<td class='{cell_class('eq_gold_price')}' data-value='{row['eq_gold_price']:.0f}'>{fmt_int(row['eq_gold_price'])}</td>"
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
    height: 100%;
    margin: 0;
    padding: 0;
    background: transparent;
    overflow: hidden;
    font-family: "Source Sans Pro", sans-serif;
}}
.table-scroll {{
    height: auto;
    overflow-x: auto;
    overflow-y: hidden;
}}
.bubble-table {{
    width: 100%;
    min-width: 1230px;
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
    position: sticky;
    top: 0;
    z-index: 2;
    background: #1c2433;
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
.bubble-table th.fund-header {{
    left: 0;
    z-index: 4;
}}
.bubble-table td.fund {{
    position: sticky;
    left: 0;
    z-index: 1;
    box-shadow: 2px 0 4px rgba(15, 23, 42, 0.25);
}}
.bubble-table th.num-header,
.bubble-table td.num {{
    text-align: center;
    font-variant-numeric: tabular-nums;
    font-family: "SF Mono", "Menlo", monospace;
    white-space: nowrap;
}}
.bubble-table td.sparkline-cell {{
    padding: 4px 6px;
    text-align: center;
    direction: ltr;
}}
.sparkline {{
    display: block;
    width: 100px;
    height: 30px;
    margin: 0 auto;
    border-radius: 4px;
    background: rgba(255, 255, 255, 0.88);
}}
.sparkline-zero {{
    stroke: #94a3b8;
    stroke-width: 0.7;
    stroke-dasharray: 2 2;
}}
.sparkline-empty {{ color: #94a3b8; }}
.sparkline-cell {{ cursor: zoom-in; }}
.trend-overlay {{
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    z-index: 20;
    display: flex;
    align-items: flex-start;
    justify-content: center;
    padding: 16px;
    background: rgba(15, 23, 42, 0.72);
}}
.trend-dialog {{
    position: relative;
    width: min(760px, 100%);
    padding: 18px;
    border: 1px solid #cbd5e1;
    border-radius: 12px;
    background: #ffffff;
    box-shadow: 0 20px 60px rgba(15, 23, 42, 0.35);
}}
.trend-dialog-title {{
    margin: 0 36px 12px 0;
    color: #0f172a;
    font-size: 1rem;
    font-weight: 700;
    text-align: right;
    direction: rtl;
}}
.trend-chart-svg {{
    display: block;
    width: 100%;
    height: 320px;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    background: #f8fafc;
}}
.trend-chart-svg .chart-grid {{ stroke: #e2e8f0; stroke-width: 1; }}
.trend-chart-svg .chart-zero {{ stroke: #94a3b8; stroke-width: 1.2; stroke-dasharray: 4 4; }}
.trend-chart-svg .chart-axis {{ stroke: #94a3b8; stroke-width: 1; }}
.trend-chart-svg .chart-line {{ fill: none; stroke-width: 2.6; stroke-linecap: round; stroke-linejoin: round; }}
.trend-chart-svg .chart-label {{ fill: #475569; font: 12px "SF Mono", "Menlo", monospace; }}
.trend-chart-svg .chart-axis-title {{ fill: #334155; font: 600 12px "Source Sans Pro", sans-serif; }}
.trend-dialog-meta {{
    margin: -4px 0 12px;
    color: #64748b;
    font-size: 0.72rem;
    text-align: right;
    direction: rtl;
}}
.trend-close {{
    position: absolute;
    top: 10px;
    left: 10px;
    width: 28px;
    height: 28px;
    border: 0;
    border-radius: 50%;
    background: #e2e8f0;
    color: #334155;
    cursor: pointer;
    font-size: 1.2rem;
    line-height: 1;
}}
.trend-close:hover {{ background: #cbd5e1; }}
.bubble-table td.cell-flash-up {{ animation: cell-flash-up 2.5s ease-out; }}
.bubble-table td.cell-flash-down {{ animation: cell-flash-down 2.5s ease-out; }}
@keyframes cell-flash-up {{
    0%, 45% {{ background: #86efac; color: #064e3b; }}
    100% {{ background: transparent; }}
}}
@keyframes cell-flash-down {{
    0%, 45% {{ background: #fca5a5; color: #7f1d1d; }}
    100% {{ background: transparent; }}
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
.bubble-table tbody tr:nth-child(odd) td.fund {{ background: #ffffff; }}
.bubble-table tbody tr:nth-child(even) {{
    background: #3b82f6;
    color: #ffffff;
}}
.bubble-table tbody tr:nth-child(even) td.fund {{ background: #3b82f6; }}
.bubble-table td.fund {{
    text-align: right;
    direction: rtl;
    cursor: help;
}}
.fund-symbol {{
    display: block;
    font-weight: 700;
    font-size: 0.78rem;
    line-height: 1.15;
}}
.fund-name {{
    display: block;
    margin-top: 2px;
    font-size: 0.52rem;
    font-weight: 400;
    line-height: 1.25;
    opacity: 0.78;
    white-space: normal;
    overflow-wrap: anywhere;
}}
.pin-toggle {{
    border: 0;
    padding: 0 4px 0 0;
    background: transparent;
    color: inherit;
    cursor: pointer;
    font: inherit;
    font-size: 1rem;
    line-height: 1;
    vertical-align: -0.08em;
    opacity: 0.55;
}}
.pin-toggle.is-pinned {{
    color: #f7c948;
    opacity: 1;
}}
</style>
</head>
<body>
<div class="table-scroll">
<table class="bubble-table" id="funds-table">
<colgroup>
<col style="width:220px">
<col style="width:112px">
<col style="width:110px">
<col style="width:145px">
<col style="width:145px">
<col style="width:125px">
<col style="width:125px">
<col style="width:100px">
<col style="width:150px">
</colgroup>
<thead>
<tr>
<th class="fund-header">Fund</th>
<th>Bubble Trend (50D)</th>
<th class="sortable num-header" data-col="2">Bubble %<span class="sort-indicator"></span></th>
<th class="sortable num-header" data-col="3">Avg Bubble(50D)<span class="sort-indicator"></span></th>
<th class="sortable num-header" data-col="4">Bubble Deviation (50D)<span class="sort-indicator"></span></th>
<th class="sortable num-header" data-col="5">Last Price<span class="sort-indicator"></span></th>
<th class="sortable num-header" data-col="6">NAV<span class="sort-indicator"></span></th>
<th class="sortable num-header" data-col="7">GF Ratio<span class="sort-indicator"></span></th>
<th class="sortable num-header" data-col="8">EqGold Price<span class="sort-indicator"></span></th>
</tr>
</thead>
<tbody>
{tbody}
</tbody>
</table>
</div>
<script>
const sortState = {{}};
const pinnedStorageKey = "nav-bubble-dashboard-pinned-funds";
let memoryPinnedSymbols = new Set();

function pinnedSymbols() {{
    try {{
        return new Set(JSON.parse(localStorage.getItem(pinnedStorageKey)) || []);
    }} catch {{
        return new Set(memoryPinnedSymbols);
    }}
}}

function savePinnedSymbols(symbols) {{
    memoryPinnedSymbols = new Set(symbols);
    try {{
        localStorage.setItem(pinnedStorageKey, JSON.stringify([...symbols]));
    }} catch {{
        // The table remains usable even if the embedded frame cannot persist state.
    }}
}}

function renderPin(row, isPinned) {{
    row.dataset.pinned = String(isPinned);
    const button = row.querySelector(".pin-toggle");
    button.textContent = isPinned ? "★" : "☆";
    button.classList.toggle("is-pinned", isPinned);
    button.title = isPinned ? "Unpin this fund" : "Pin this fund";
    button.setAttribute("aria-pressed", String(isPinned));
}}

function restorePinnedRows() {{
    const symbols = pinnedSymbols();
    document.querySelectorAll("tbody tr").forEach((row) => {{
        renderPin(row, symbols.has(row.dataset.symbol));
    }});
}}

function sortTable(colIdx) {{
    const table = document.getElementById("funds-table");
    const tbody = table.querySelector("tbody");
    const rows = Array.from(tbody.querySelectorAll("tr"));
    const asc = sortState[colIdx] !== "asc";
    Object.keys(sortState).forEach((key) => delete sortState[key]);
    sortState[colIdx] = asc ? "asc" : "desc";

    rows.sort((a, b) => {{
        const aPinned = a.dataset.pinned === "true";
        const bPinned = b.dataset.pinned === "true";
        if (aPinned !== bPinned) return aPinned ? -1 : 1;
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

document.querySelectorAll(".pin-toggle").forEach((button) => {{
    button.addEventListener("click", () => {{
        const row = button.closest("tr");
        const symbols = pinnedSymbols();
        const isPinned = !symbols.has(row.dataset.symbol);
        if (isPinned) symbols.add(row.dataset.symbol);
        else symbols.delete(row.dataset.symbol);
        savePinnedSymbols(symbols);
        renderPin(row, isPinned);
        const activeColumn = Object.keys(sortState)[0];
        if (activeColumn !== undefined) sortTable(Number(activeColumn));
    }});
}});

function closeTrendOverlay() {{
    document.querySelector(".trend-overlay")?.remove();
}}

function buildTrendChart(points) {{
    const values = points.map((point) => Number(point.value)).filter(Number.isFinite);
    if (values.length < 2) return null;

    const width = 720;
    const height = 360;
    const margin = {{ top: 24, right: 20, bottom: 58, left: 68 }};
    const plotWidth = width - margin.left - margin.right;
    const plotHeight = height - margin.top - margin.bottom;
    let minValue = Math.min(...values);
    let maxValue = Math.max(...values);
    if (minValue === maxValue) {{
        minValue -= 1;
        maxValue += 1;
    }}
    const padding = (maxValue - minValue) * 0.08;
    minValue -= padding;
    maxValue += padding;
    const x = (index) => margin.left + (index / (values.length - 1)) * plotWidth;
    const y = (value) => margin.top + ((maxValue - value) / (maxValue - minValue)) * plotHeight;
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", `0 0 ${{width}} ${{height}}`);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "Bubble Trend chart");
    svg.classList.add("trend-chart-svg");
    const add = (tag, attrs, textContent = "") => {{
        const element = document.createElementNS(ns, tag);
        Object.entries(attrs).forEach(([key, value]) => element.setAttribute(key, value));
        if (textContent) element.textContent = textContent;
        svg.appendChild(element);
        return element;
    }};

    add("line", {{ x1: margin.left, y1: margin.top + plotHeight, x2: width - margin.right, y2: margin.top + plotHeight, class: "chart-axis" }});
    add("line", {{ x1: margin.left, y1: margin.top, x2: margin.left, y2: margin.top + plotHeight, class: "chart-axis" }});
    for (let index = 0; index <= 4; index += 1) {{
        const value = minValue + ((maxValue - minValue) * index) / 4;
        const yPosition = y(value);
        add("line", {{ x1: margin.left, y1: yPosition, x2: width - margin.right, y2: yPosition, class: "chart-grid" }});
        add("text", {{ x: margin.left - 10, y: yPosition + 4, class: "chart-label", "text-anchor": "end" }}, value.toFixed(2) + "%");
    }}
    if (minValue < 0 && maxValue > 0) {{
        const zeroPosition = y(0);
        add("line", {{ x1: margin.left, y1: zeroPosition, x2: width - margin.right, y2: zeroPosition, class: "chart-zero" }});
    }}
    add("polyline", {{
        points: values.map((value, index) => x(index) + "," + y(value)).join(" "),
        class: "chart-line",
        stroke: values[values.length - 1] > 0 ? "#b91c1c" : values[values.length - 1] < 0 ? "#15803d" : "#475569",
    }});
    const tickIndexes = [...new Set([0, Math.floor((values.length - 1) / 2), values.length - 1])];
    tickIndexes.forEach((index) => {{
        add("line", {{ x1: x(index), y1: margin.top + plotHeight, x2: x(index), y2: margin.top + plotHeight + 6, class: "chart-axis" }});
        add("text", {{ x: x(index), y: height - 26, class: "chart-label", "text-anchor": "middle" }}, points[index]?.date || "");
    }});
    add("text", {{ x: margin.left, y: 14, class: "chart-axis-title", "text-anchor": "start" }}, "Bubble %");
    add("text", {{ x: width - margin.right, y: height - 6, class: "chart-axis-title", "text-anchor": "end" }}, "Date");
    return svg;
}}

function openTrendOverlay(cell) {{
    let points = [];
    try {{
        points = JSON.parse(cell.dataset.trend || "[]");
    }} catch {{
        return;
    }}
    const chart = buildTrendChart(points);
    if (!chart) return;
    closeTrendOverlay();
    const row = cell.closest("tr");
    const overlay = document.createElement("div");
    overlay.className = "trend-overlay";
    overlay.innerHTML = `
        <div class="trend-dialog" role="dialog" aria-modal="true">
            <button class="trend-close" type="button" aria-label="Close">×</button>
            <div class="trend-dialog-title"></div>
            <div class="trend-dialog-meta"></div>
            <div class="trend-chart"></div>
        </div>`;
    overlay.querySelector(".trend-dialog-title").textContent =
        `${{row.dataset.symbol}} · ${{row.querySelector(".fund-name")?.textContent || ""}} · Bubble Trend (50D)`;
    overlay.querySelector(".trend-dialog-meta").textContent =
        `${{points.length}} observations · ${{points[0]?.date || ""}} → ${{points[points.length - 1]?.date || ""}}`;
    overlay.querySelector(".trend-chart").appendChild(chart);
    overlay.querySelector(".trend-close").addEventListener("click", closeTrendOverlay);
    overlay.addEventListener("click", (event) => {{
        if (event.target === overlay) closeTrendOverlay();
    }});
    document.body.appendChild(overlay);
    const dialog = overlay.querySelector(".trend-dialog");
    const documentHeight = Math.max(document.documentElement.scrollHeight, document.body.scrollHeight);
    overlay.style.height = `${{documentHeight}}px`;
    const rowTop = row.getBoundingClientRect().top + window.scrollY;
    const maxTop = Math.max(16, documentHeight - dialog.offsetHeight - 16);
    dialog.style.marginTop = `${{Math.min(Math.max(16, rowTop + row.offsetHeight / 2 - dialog.offsetHeight / 2), maxTop)}}px`;
    overlay.querySelector(".trend-close").focus();
}}

document.querySelectorAll(".sparkline-cell").forEach((cell) => {{
    cell.addEventListener("click", () => openTrendOverlay(cell));
    cell.addEventListener("keydown", (event) => {{
        if (event.key === "Enter" || event.key === " ") {{
            event.preventDefault();
            openTrendOverlay(cell);
        }}
    }});
}});

document.addEventListener("keydown", (event) => {{
    if (event.key === "Escape") closeTrendOverlay();
}});

restorePinnedRows();
sortTable(2);
</script>
</body>
</html>"""


@st.fragment
def render_dashboard() -> None:
    collect_finished_refresh()
    df = get_data()
    if df.empty:
        if st.button("🔄 Refresh"):
            run_manual_refresh()
        st.warning("No local snapshot is available yet. Push Refresh to fetch data from TSETMC.")
        return

    history = get_history(df)
    fetch_time = df["observed_at"].max().tz_convert(TZ)
    daily_history = (
        history.dropna(subset=["nav_bubble"])
        .sort_values(["symbol", "market_date", "observed_at"])
        .copy()
    )
    daily_history["avg_bubble_50"] = daily_history.groupby("symbol")["nav_bubble"].transform(
        lambda values: values.rolling(50, min_periods=50).mean()
    )
    latest_rolling_avg = (
        daily_history.groupby("symbol", as_index=False)
        .tail(1)[["symbol", "avg_bubble_50"]]
    )
    daily_history["trend_date"] = daily_history["market_date"]
    bubble_trends = {
        symbol: [
            {"date": date, "value": float(value)}
            for date, value in frame.tail(50)[["trend_date", "nav_bubble"]].itertuples(index=False)
        ]
        for symbol, frame in daily_history.groupby("symbol")
    }
    bubble = (
        df[
            [
                "symbol",
                "fund_name",
                "nav_bubble",
                "last_price",
                "nav",
            ]
        ]
        .dropna(subset=["nav_bubble"])
        .merge(load_conversion(), on="symbol", how="left")
        .merge(latest_rolling_avg, on="symbol", how="left")
        .sort_values("nav_bubble", ascending=False)
        .reset_index(drop=True)
    )
    bubble["bubble_deviation"] = bubble["nav_bubble"] - bubble["avg_bubble_50"]
    bubble["bubble_trend"] = bubble["symbol"].map(bubble_trends)
    bubble["eq_gold_price"] = bubble["last_price"] * bubble["Gold Fund Ratio"]
    cell_flashes = changed_cell_classes(bubble)

    top_left, download_col, refresh_col = st.columns([3, 1, 1])
    with refresh_col:
        manual_refresh = st.button("🔄 Refresh", use_container_width=True)
    if manual_refresh:
        run_manual_refresh()

    status_class, status_label, status_detail = refresh_badge(fetch_time)
    with top_left:
        st.markdown(
            f"""
            <div class="top-bar">
                <span class="fetch-chip">
                    <span class="fetch-dot {status_class}"></span>
                    {status_label}&nbsp;·&nbsp;{status_detail}
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with download_col:
        st.download_button(
            "⬇️ Download CSV",
            data=build_download_csv(bubble),
            file_name=f"gold_funds_{fetch_time.strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    table_height = 58 + len(bubble) * 58
    components.html(
        build_table_html(
            bubble,
            cell_flashes=cell_flashes,
        ),
        height=table_height,
        scrolling=False,
    )


render_dashboard()
