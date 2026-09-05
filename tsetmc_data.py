import os
import tempfile
from concurrent.futures import ThreadPoolExecutor

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
    "observed_at",
    "market_date",
    "last_price",
    "nav",
    "nav_bubble",
]

TSETMC_BASE = "https://cdn.tsetmc.com/api"
HEADERS = {"User-Agent": "Mozilla/5.0"}

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


def _fetch_price_info(idx: str) -> dict:
    url = f"{TSETMC_BASE}/ClosingPrice/GetClosingPriceInfo/{idx}"
    data = requests.get(url, headers=HEADERS, timeout=5).json()["closingPriceInfo"]
    market_date = data.get("dEven") or data.get("finalLastDate")
    if not market_date:
        raise ValueError("TSETMC did not return a market date")
    return {"last_price": data["pDrCotVal"], "market_date": str(market_date)}


def _fetch_nav(idx: str) -> float:
    url = f"{TSETMC_BASE}/Fund/GetETFByInsCode/{idx}"
    resp = requests.get(url, headers=HEADERS, timeout=5)
    resp.raise_for_status()
    etf = resp.json()["etf"]
    return etf.get("pRedTran") or etf.get("pSubTran") or 0.0


def _collect_one_fund(key: str, idx: str) -> dict:
    row = {"symbol": key, "fund_name": FUND_NAMES[key], "observed_at": datetime.now(TZ)}
    row.update(_fetch_price_info(idx))
    row["nav"] = _fetch_nav(idx)
    row["nav_bubble"] = (
        (row["last_price"] - row["nav"]) / row["nav"] * 100
        if row["nav"]
        else None
    )
    return row


def normalize_snapshot(frame: pd.DataFrame) -> pd.DataFrame:
    """Use market session dates; migrate legacy ``created_at`` CSVs on read."""
    normalized = frame.copy()
    if "observed_at" not in normalized.columns:
        normalized["observed_at"] = normalized["created_at"]
    observed_at = pd.to_datetime(normalized["observed_at"], format="mixed", utc=True)
    normalized["observed_at"] = observed_at.dt.tz_convert(TZ)

    if "market_date" not in normalized.columns:
        normalized["market_date"] = normalized["observed_at"].dt.strftime("%Y-%m-%d")
    else:
        market_dates = pd.to_datetime(
            normalized["market_date"].astype(str), format="mixed", errors="coerce"
        )
        normalized["market_date"] = market_dates.dt.strftime("%Y-%m-%d")
        if normalized["market_date"].isna().any():
            raise ValueError("TSETMC returned an invalid market date")

    if "fund_name" not in normalized.columns:
        normalized.insert(1, "fund_name", normalized["symbol"].map(FUND_NAMES))
    else:
        normalized["fund_name"] = normalized["fund_name"].fillna(
            normalized["symbol"].map(FUND_NAMES)
        )
    return normalized[COL_ORDER]


def collect_gold_funds_data() -> pd.DataFrame:
    rows = []
    with ThreadPoolExecutor(max_workers=min(8, len(symbols))) as executor:
        futures = {
            key: executor.submit(_collect_one_fund, key, idx)
            for key, idx in symbols.items()
        }
        for key, idx in symbols.items():
            try:
                rows.append(futures[key].result())
            except Exception as error:
                print(f"Skipping {key} ({idx}): {error}")
                # A partial market snapshot is not safe to publish as the latest view.
                return pd.DataFrame(columns=COL_ORDER)

    if not rows:
        return pd.DataFrame(columns=COL_ORDER)
    return pd.DataFrame(rows)[COL_ORDER]


def write_csv_atomic(frame: pd.DataFrame, path: Path) -> None:
    """Publish a complete CSV snapshot without exposing a partially written file."""
    # Use a unique temporary file: multiple Streamlit sessions can refresh at
    # the same time, and sharing one ``.tmp`` path can interleave their writes.
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            frame.to_csv(handle, index=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def append_daily_snapshot(snapshot: pd.DataFrame) -> pd.DataFrame:
    """Keep the latest snapshot for each fund in each TSETMC market session."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    current = normalize_snapshot(snapshot)
    if HISTORY_CSV_PATH.exists():
        history = pd.concat(
            [normalize_snapshot(pd.read_csv(HISTORY_CSV_PATH)), current], ignore_index=True
        )
    else:
        history = current
    history = (
        history.sort_values("observed_at")
        .drop_duplicates(["symbol", "market_date"], keep="last")
        .sort_values(["symbol", "market_date", "observed_at"])
        .reset_index(drop=True)
    )
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
