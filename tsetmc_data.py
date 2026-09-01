import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=3, minutes=30))
PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data"
CSV_PATH = DATA_DIR / "gold_funds.csv"
HISTORY_CSV_PATH = DATA_DIR / "gold_funds_history.csv"
COL_ORDER = [
    "symbol",
    "fund_name",
    "created_at",
    "last_price",
    "nav",
    "nav_bubble",
]

TSETMC_BASE = "https://cdn.tsetmc.com/api"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.tsetmc.com/",
    "Origin": "https://www.tsetmc.com",
}

symbols = {
    "طلا": "46700660505281786" , "آلتون": "28374437855144739", "زر": "33254899395816171", "درنا": "17248898258246807", "گلدیس": "68376789401977331", "لیان": "6362118829011821",
    "ناب": "30582275818828857", "گوهر": "12390706505809150", "آتش": "56987424987755487", "قیراط": "6237807001018762", "زرگر": "16817885126368964",
    "زروان": "28255729477187163", "مثقال": "32469128621155736", "نفیس": "4626686276232042", "امرالد": "30895446582685604", "زرفام": "33144542989832366", "درخشان": "61805666737517582",
    "تابش": "9089296888187061", "ریتون": "14035144070182412", "جواهر": "38544104313215500", "زمرد": "64795751499397128", "عیار": "34144395039913458", "گنج": "58514988269776425",
    "گلدا": "48968268685622891", "کهربا": "25559236668122210", "جام طلا": "35389487611786089", "میراث": "53633583359422860", "نگین فارس": "53514992320442853", 
    "همیان": "50072269736641214", "رزگلد": "17244733069907210", "رز ترنج": "20244389840999638"
}

# Long legal/display names copied from the Bourseview fund titles.
FUND_NAMES = {
    "طلا": "صندوق س. کالای پارسیان",
    "گوهر": "صندوق س.کالای کیان",
    "عیار": "صندوق طلای عیار مفید",
    "کهربا": "صندوق س. کالای کهربا",
    "مثقال": "صندوق س.کالای آگاه",
    "زرفام": "صندوق س.کالای آشنا",
    "نفیس": "صندوق س.کالای صبا",
    "گنج": "صندوق س. سیمای کاردان",
    "ناب": "صندوق س.پشتوانه طلا نهایت نگر",
    "آلتون": "صندوق س. کالای آسمان",
    "جواهر": "صندوق س.کالای دنای زاگرس",
    "تابش": "صندوق س.کالای تابان تمدن",
    "زروان": "صندوق س.کالای ویستا",
    "درخشان": "صندوق س.کالای آبان",
    "لیان": "صندوق س.کالای دیبای معیار",
    "آتش": "صندوق س.کالای کهکشان فیروزه",
    "قیراط": "صندوق س.کالای درفش دماوند",
    "زمرد": "صندوق س.کالای زمرد بیدار",
    "امرالد": "صندوق س. کالای کیمیا",
    "گلدیس": "صندوق س.پشتوانه طلا گلدیس نوین",
    "رز ترنج": "صندوق س.کالای ترنج",
    "درنا": "صندوق س.پشتوانه طلای درنا",
    "زرگر": "صندوق س.کالای کارآمد",
    "ریتون": "صندوق س. کالای پاسارگاد",
    "گلدا": "صندوق س.کالای پاداش",
    "رزگلد": "صندوق س. کالای آرمان آتی",
    "جام طلا": "صندوق س.مبتنی بر کالای فارابی",
    "نگین فارس": "صندوق س.طلا زردیس خلیج فارس",
    "همیان": "صندوق س.پشتوانه طلا همیان سپهر",
    "میراث": "صندوق س.کالای کوروش",
    "زر": "صندوق س.کالای امید ثروت ایران",
}


def _request_json(url: str) -> dict:
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=6)
            resp.raise_for_status()
            return resp.json()
        except Exception as error:
            last_error = error
            if "Failed to resolve" in str(error) or "NameResolutionError" in type(error).__name__:
                break
            time.sleep(0.3 * (attempt + 1))
    raise last_error or RuntimeError(f"Failed to fetch {url}")


def _fetch_price_info(idx: str) -> dict:
    url = f"{TSETMC_BASE}/ClosingPrice/GetClosingPriceInfo/{idx}"
    data = _request_json(url)["closingPriceInfo"]
    return {"last_price": data["pDrCotVal"]}


def _fetch_nav(idx: str) -> float:
    url = f"{TSETMC_BASE}/Fund/GetETFByInsCode/{idx}"
    etf = _request_json(url)["etf"]
    return etf.get("pRedTran") or etf.get("pSubTran") or 0.0


def _fetch_fund(key: str, idx: str) -> dict:
    row = {"symbol": key, "fund_name": FUND_NAMES[key]}
    row.update(_fetch_price_info(idx))
    row["nav"] = _fetch_nav(idx)
    row["nav_bubble"] = (row["last_price"] - row["nav"]) / row["nav"] * 100 if row["nav"] else None
    return row


def collect_gold_funds_data() -> pd.DataFrame:
    rows = []
    errors = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_fetch_fund, key, idx): key for key, idx in symbols.items()}
        for future in as_completed(futures):
            key = futures[future]
            try:
                rows.append(future.result())
            except Exception as error:
                errors.append(f"{key}: {error}")
                print(f"Skipping {key}: {error}")

    if errors or len(rows) != len(symbols):
        # A partial market snapshot is not safe to publish as the latest view.
        return pd.DataFrame(columns=COL_ORDER)

    fetched_at = datetime.now(TZ)
    for row in rows:
        row["created_at"] = fetched_at
    return pd.DataFrame(rows)[COL_ORDER]


def write_csv_atomic(frame: pd.DataFrame, path: Path) -> None:
    """Publish a complete CSV snapshot without exposing a partially written file."""
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary_path, index=False)
    os.replace(temporary_path, path)


def append_daily_snapshot(snapshot: pd.DataFrame) -> pd.DataFrame:
    """Keep the latest snapshot for each fund on each Tehran calendar day."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    current = snapshot.copy()
    if "fund_name" not in current.columns:
        current.insert(1, "fund_name", current["symbol"].map(FUND_NAMES))
    else:
        current["fund_name"] = current["fund_name"].fillna(current["symbol"].map(FUND_NAMES))
    current = current[COL_ORDER]
    if HISTORY_CSV_PATH.exists():
        history = pd.concat([pd.read_csv(HISTORY_CSV_PATH), current], ignore_index=True)
    else:
        history = current

    if "fund_name" not in history.columns:
        history.insert(1, "fund_name", history["symbol"].map(FUND_NAMES))
    else:
        history["fund_name"] = history["fund_name"].fillna(history["symbol"].map(FUND_NAMES))
    history = history[COL_ORDER]

    history["created_at"] = pd.to_datetime(history["created_at"], format="mixed", utc=True)
    history["_date"] = history["created_at"].dt.tz_convert(TZ).dt.date
    history = (
        history.sort_values("created_at")
        .drop_duplicates(["symbol", "_date"], keep="last")
        .drop(columns="_date")
        .sort_values(["symbol", "created_at"])
        .reset_index(drop=True)
    )
    history["created_at"] = history["created_at"].dt.tz_convert(TZ)
    write_csv_atomic(history, HISTORY_CSV_PATH)
    return history


def main() -> int:
    df = collect_gold_funds_data()
    if len(df) != len(symbols) or df["symbol"].nunique() != len(symbols):
        print("Incomplete gold fund data was collected; existing files were left unchanged")
        return 1
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    write_csv_atomic(df, CSV_PATH)
    append_daily_snapshot(df)
    print(f"Gold funds data extracted successfully and saved to {CSV_PATH} ({len(df)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
