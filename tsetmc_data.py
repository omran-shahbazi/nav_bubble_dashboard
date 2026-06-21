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
    "tala": "46700660505281786" , "alton": "28374437855144739", "zar": "33254899395816171", "dorna": "17248898258246807", "goldis": "68376789401977331", "lian": "6362118829011821",
    "nab": "30582275818828857", "gohar": "12390706505809150", "atash": "56987424987755487", "ghirat": "6237807001018762", "zargar": "16817885126368964",
    "zarvan": "28255729477187163", "mesghal": "32469128621155736", "nafis": "4626686276232042", "emrald": "30895446582685604", "zarfam": "33144542989832366", "derakhshan": "61805666737517582",
    "tabesh": "9089296888187061", "reyton": "14035144070182412", "javaher": "38544104313215500", "zomorrod": "64795751499397128", "aiar": "34144395039913458", "ganj": "58514988269776425",
    "golda": "48968268685622891", "kahroba": "25559236668122210", "jam-e-tala": "35389487611786089", "miras": "53633583359422860", "negin-e-fars": "53514992320442853", 
    "hamian": "50072269736641214", "rozgold": "17244733069907210",
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
