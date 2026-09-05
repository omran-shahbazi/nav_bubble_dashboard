import requests
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=3, minutes=30))
PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data"
CSV_PATH = DATA_DIR / "gold_funds.csv"
COL_ORDER = [
    "symbol",
    "created_at",
    "last_price",
    "volume",
    "nav",
    "nav_bubble",
    "best_ask_price",
    "best_ask_volume",
    "best_bid_price",
    "best_bid_volume",
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


def _fetch_price_info(idx: str) -> dict:
    url = f"{TSETMC_BASE}/ClosingPrice/GetClosingPriceInfo/{idx}"
    data = requests.get(url, headers=HEADERS, timeout=10).json()["closingPriceInfo"]
    return {"last_price": data["pDrCotVal"], "volume": data["qTotTran5J"]}


def _fetch_nav(idx: str) -> float:
    url = f"{TSETMC_BASE}/Fund/GetETFByInsCode/{idx}"
    resp = requests.get(url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    etf = resp.json()["etf"]
    return etf.get("pRedTran") or etf.get("pSubTran") or 0.0


def _fetch_best_limits(idx: str) -> dict:
    url = f"{TSETMC_BASE}/BestLimits/{idx}"
    limits = requests.get(url, headers=HEADERS, timeout=10).json()["bestLimits"]
    if not limits:
        return {"best_ask_price": None, "best_ask_volume": None,
                "best_bid_price": None, "best_bid_volume": None}
    top = limits[0]
    return {
        "best_ask_price": top["pMeOf"],
        "best_ask_volume": top["qTitMeOf"],
        "best_bid_price": top["pMeDem"],
        "best_bid_volume": top["qTitMeDem"],
    }


def collect_gold_funds_data() -> pd.DataFrame:
    rows = []
    for key, idx in symbols.items():
        try:
            row = {"symbol": key, "created_at": datetime.now(TZ)}
            row.update(_fetch_price_info(idx))
            row["nav"] = _fetch_nav(idx)
            row["nav_bubble"] = (row["last_price"] - row["nav"]) / row["nav"] * 100 if row["nav"] else None
            row.update(_fetch_best_limits(idx))
            rows.append(row)
        except Exception as e:
            print(f"Skipping {key} ({idx}): {e}")

    if not rows:
        return pd.DataFrame(columns=COL_ORDER)
    return pd.DataFrame(rows)[COL_ORDER]


def main() -> int:
    df = collect_gold_funds_data()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(CSV_PATH, index=False)
    print(f"Gold funds data extracted successfully and saved to {CSV_PATH} ({len(df)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
