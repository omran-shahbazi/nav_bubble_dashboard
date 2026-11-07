import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import silver_data as data

st.set_page_config(page_title="حباب صندوق‌های نقره", page_icon="🥈", layout="wide")

TEMPLATE = (Path(__file__).parent / "dashboard.html").read_text(encoding="utf-8")
LIVE_TTL_SECONDS = 10   # how often data is fetched and the open page updates itself
FROM_COLLECTOR = os.environ.get("SNAPSHOT_FROM_COLLECTOR") == "1"  # set in the Dockerfile

def config() -> dict:
    now = int(time.time())
    start = now - 400 * 86400
    return {
        "troy_ounce_grams": data.TROY_OUNCE_GRAMS,
        "target_purity": data.TARGET_PURITY,
        "ime_purity": data.IME_PURITY,
        "min_trading_days": data.MIN_TRADING_DAYS,
        "refresh_seconds": LIVE_TTL_SECONDS,
        "urls": {
            "lighter_live": f"{data.LIGHTER}/orderBookDetails?market_id={data.LIGHTER_XAG_MARKET}",
            "lighter_hist": f"{data.LIGHTER}/candles?market_id={data.LIGHTER_XAG_MARKET}&resolution=1d"
                            f"&start_timestamp={start}000&end_timestamp={now}000&count_back=400",
            "lighter_page": "https://app.lighter.xyz/trade/XAG",
            "wallex_live": f"{data.WALLEX}/markets",
            "wallex_hist": f"{data.WALLEX}/udf/history?symbol=USDTTMN&resolution=D&from={start}&to={now}",
            "wallex_page": "https://wallex.ir/app/trade/USDTTMN",
            "ime_live": f"{data.IME_API}/CDCLiveMarket",
            "ime_page": "https://silver.ime.co.ir/",
            "ime_hist_page": "https://silver.ime.co.ir/Main/TransactionStatistics",
            "ime_hist_api": f"POST {data.IME_API}/CDCTrades (customFilter={data.IME_SILVER_ID})",
            "tsetmc_price": f"{data.TSETMC}/ClosingPrice/GetClosingPriceInfo/",
            "tsetmc_nav": f"{data.TSETMC}/Fund/GetETFByInsCode/",
            "tsetmc_daily": f"{data.TSETMC}/ClosingPrice/GetClosingPriceDailyList/",
            "tsetmc_page": "https://www.tsetmc.com/instInfo/",
            "fipiran_page": "https://www.fipiran.com/",
            "fundbase": "https://app.fundbase.ir/categories/نقره",
            "fundbase_fund": "https://app.fundbase.ir/funds/",
        },
    }


st.markdown(
    """
<style>
@font-face { font-family: "Vazirmatn"; src: url("app/static/fonts/Vazirmatn.woff2") format("woff2"); font-weight: 100 900; font-display: swap; }
#MainMenu, footer, header {visibility: hidden;}
header[data-testid="stHeader"] {display: none;}
.block-container { padding-top: 1rem; padding-bottom: 1rem; max-width: 100%; overflow: visible; }
[data-testid="stVerticalBlock"]:has(.top-bar) { gap: 0.25rem; }
.top-bar { margin-bottom: 0.35rem; }
[data-testid="stMarkdownContainer"] p { overflow: visible; line-height: normal; margin: 0; padding: 0; }
[data-testid="stHorizontalBlock"] { margin-bottom: 0.35rem; align-items: center; }
[data-testid="stMarkdownContainer"], [data-testid="column"] { overflow: visible; }
[data-testid="stButton"] { padding-top: 0.35rem; padding-bottom: 0.35rem; }
.fetch-chip {
    display: inline-flex; align-items: center; gap: 8px;
    background: #1c2433; border: 1px solid #2e3a4f; color: #cdd6e4;
    font-size: 0.85rem; line-height: 1.4; padding: 8px 14px; border-radius: 999px;
    font-family: 'Vazirmatn', Tahoma, sans-serif; vertical-align: middle; direction: rtl;
}
.top-bar { text-align: right; }
[data-testid="stButton"] button, [data-testid="stDownloadButton"] button { font-family: 'Vazirmatn', Tahoma, sans-serif; }
.fetch-dot { width: 8px; height: 8px; border-radius: 50%; }
.fetch-dot.live { background: #34d399; box-shadow: 0 0 8px #34d399; }
.fetch-dot.cached { background: #fbbf24; box-shadow: 0 0 8px #fbbf24; }
iframe[title="streamlit_components_v1"] { border: none; }
</style>
""",
    unsafe_allow_html=True,
)


class SnapshotFeed:
    """Keeps the latest snapshot in memory. A background thread refetches it every
    LIVE_TTL_SECONDS, so a page renders immediately instead of waiting on the sources;
    until the first fetch finishes, the last snapshot saved on disk is shown."""

    def __init__(self):
        self._lock = threading.Lock()  # one fetch at a time
        self.snap = data.load_saved_snapshot()
        self.fresh = False
        self.error = None
        threading.Thread(target=self._loop, name="snapshot-feed", daemon=True).start()

    def refresh(self) -> None:
        if not self._lock.acquire(blocking=False):
            # A fetch is already running; wait for it rather than starting a second one.
            with self._lock:
                return
        try:
            # On the server collector.py fetches; the app only reads what it saved.
            snap = data.load_saved_snapshot() if FROM_COLLECTOR else data.build_snapshot()
            if snap and snap.get("funds"):
                self.snap, self.fresh, self.error = snap, True, None
        except Exception as exc:  # noqa: BLE001 - keep showing the last good snapshot
            self.error = str(exc)
        finally:
            self._lock.release()

    def _loop(self) -> None:
        while True:
            self.refresh()
            time.sleep(LIVE_TTL_SECONDS)


@st.cache_resource
def snapshot_feed() -> SnapshotFeed:
    return SnapshotFeed()


def get_snapshot() -> tuple[dict, bool]:
    feed = snapshot_feed()
    if FROM_COLLECTOR:
        feed.refresh()  # just re-reads collector.py's latest file
    if feed.snap is None:
        with st.spinner("در حال دریافت داده‌های بازار…"):
            feed.refresh()
    if feed.snap is None:
        st.error("داده‌ای در دسترس نیست: دریافت از همه منابع ناموفق بود و نسخه ذخیره‌شده‌ای هم وجود ندارد.")
        st.stop()
    if feed.error:
        st.toast(f"آخرین دریافت ناموفق بود؛ آخرین داده سالم نمایش داده می‌شود: {feed.error}")
    fetched = datetime.strptime(feed.snap["fetched_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=data.TEHRAN)
    recent = (datetime.now(data.TEHRAN) - fetched).total_seconds() < 3 * LIVE_TTL_SECONDS
    return feed.snap, feed.fresh and recent


def fa_digits(s: str) -> str:
    return s.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def funds_csv(snap: dict) -> bytes:
    rows = [{
        "Symbol": f["symbol"], "Name": f["name"], "Bubble %": f["bubble"], "Avg Bubble(50D)": f["avg_bubble"],
        "Bubble Deviation (50D)": f["deviation"], "Last Price (IRR)": f["last"], "NAV (IRR)": f["nav"],
        "SF Ratio": f["sf"], "EqSilver Price (IRR)": f["eq_silver"], "Avg days": f["avg_window"]["n"],
        "SF days": f["sf_window"]["n"], "insCode": f["insCode"], "regNo": f["regNo"],
    } for f in snap["funds"]]
    return pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig")


@st.fragment(run_every=LIVE_TTL_SECONDS)
def top_bar() -> None:
    # Reruns on its own every few seconds; the dashboard below updates itself from static/live.json.
    snap, live = get_snapshot()
    # Right to left: the status chip sits on the right, the buttons on the left.
    refresh_col, csv_col, _, chip_col = st.columns([1.3, 1.3, 3, 4])
    with chip_col:
        state, label = ("live", "زنده") if live else ("cached", "ذخیره‌شده")
        fetched = datetime.strptime(snap["fetched_at"], "%Y-%m-%d %H:%M:%S")
        when = fa_digits(f'{data.gregorian_to_jalali(fetched.date())} {fetched:%H:%M:%S}')
        st.markdown(
            f'<div class="top-bar"><span class="fetch-chip"><span class="fetch-dot {state}"></span>'
            f'{label}&nbsp;·&nbsp;آخرین به‌روزرسانی: {when} (تهران)</span></div>',
            unsafe_allow_html=True,
        )
    with csv_col:
        st.download_button("⬇️ دانلود CSV", funds_csv(snap), file_name=f"silver_funds_{snap['fetched_at'][:10]}.csv",
                           mime="text/csv", use_container_width=True)
    with refresh_col:
        if st.button("🔄 به‌روزرسانی", use_container_width=True):
            with st.spinner("در حال به‌روزرسانی…"):
                snapshot_feed().refresh()
            st.rerun()


top_bar()
snap, _ = get_snapshot()

html = (TEMPLATE
        .replace("__SNAPSHOT__", json.dumps(snap, ensure_ascii=False).replace("</", "<\\/"))
        .replace("__CONFIG__", json.dumps(config(), ensure_ascii=False)))
# Initial estimate; the page resizes its own frame once rendered and when sections are expanded.
height = 1150 + 47 * len(snap["funds"])
components.html(html, height=height, scrolling=False)
