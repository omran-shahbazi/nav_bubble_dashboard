"""Data collection for the silver NAV-bubble dashboard.

Every number the dashboard shows is computed here, together with the raw
inputs it came from, so the UI can explain each value on hover.
"""

from __future__ import annotations

import csv
import functools
import json
import math
import re
import socket
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

TEHRAN = ZoneInfo("Asia/Tehran")
TROY_OUNCE_GRAMS = 31.1034768
TARGET_PURITY = 0.925          # used only by the SF ratio / EqSilver (per gram of 925 silver)
IME_PURITY = 0.9999            # IME silver certificate = 1 g of 999.9 bullion
AVG_WINDOW = 50                # trading days for the average bubble
SF_WINDOW = 200                # trading days for the SF ratio percentile
SF_PERCENTILE = 80
MIN_TRADING_DAYS = 20          # funds with less price history are hidden from the table by default

LIGHTER = "https://mainnet.zklighter.elliot.ai/api/v1"
LIGHTER_XAG_MARKET = 93
WALLEX = "https://api.wallex.ir/v1"
IME_API = "https://dataapi.ime.co.ir/api/CDC"
IME_SILVER_CODE = "SilverBar"
IME_SILVER_ID = "21"
TSETMC = "https://cdn.tsetmc.com/api"
FIPIRAN = "https://www.fipiran.com/services"

ROOT = Path(__file__).parent
# Streamlit serves the static/ folder next to the app's entry point (app.py at the repository root).
STATIC_DIR = ROOT.parent / "static"
LIVE_PATH = STATIC_DIR / "live.json"   # latest snapshot (overwritten), served to the open page for in-place updates
# The only stored data: one row per calendar day (today's row is rewritten on every fetch, so the
# last write of the day is the end-of-day record). Its NAV columns also serve as our own NAV history.
TABLE_PATH = ROOT / "data" / "daily.csv"

_session = requests.Session()
_session.headers["User-Agent"] = "Mozilla/5.0 (silver-nav-dashboard)"


def _get(url, **kw):
    r = _session.get(url, timeout=kw.pop("timeout", 25), **kw)
    r.raise_for_status()
    return r.json()


def _post(url, payload, **kw):
    r = _session.post(url, json=payload, timeout=kw.pop("timeout", 40), **kw)
    r.raise_for_status()
    return r.json()


HISTORY_TTL = 3 * 3600   # history and identifiers barely change during the day
FAILURE_TTL = 15 * 60    # don't wait on an unreachable source on every refresh

_cache: dict = {}
_cache_lock = threading.Lock()


def cached(ttl: int):
    """Keep a function's result (or its failure) in memory, keyed by its arguments and today's date.

    Refreshes then only re-download live prices; history is reused until it expires.
    """
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args):
            key = (fn.__name__, args, tehran_today())
            with _cache_lock:
                hit = _cache.get(key)
            if hit and time.time() < hit[0]:
                if hit[1]:
                    return hit[2]
                raise hit[2]
            try:
                value = fn(*args)
            except Exception as exc:
                with _cache_lock:
                    _cache[key] = (time.time() + FAILURE_TTL, False, exc)
                raise
            with _cache_lock:
                _cache[key] = (time.time() + ttl, True, value)
            return value
        return wrapper
    return deco


def normalize_fa(text: str | None) -> str:
    return (text or "").replace("ي", "ی").replace("ك", "ک").replace("‌", "").strip()


def tehran_today() -> date:
    return tehran_now().date()


def tehran_now() -> datetime:
    return datetime.now(TEHRAN)


def deven_to_date(deven: int) -> date:
    s = str(deven)
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def percentile(values: list[float], pct: float) -> float:
    """Linear-interpolated percentile (same as numpy's default)."""
    xs = sorted(values)
    if not xs:
        return math.nan
    k = (len(xs) - 1) * pct / 100
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


# --------------------------------------------------------------------------
# Market inputs: Lighter (XAG/USD), Wallex (USDT/TMN), IME (silver certificate)
# --------------------------------------------------------------------------

def lighter_xag_live() -> dict:
    data = _get(f"{LIGHTER}/orderBookDetails", params={"market_id": LIGHTER_XAG_MARKET})
    book = next(b for b in data["order_book_details"] if b["market_id"] == LIGHTER_XAG_MARKET)
    return {"price": float(book["last_trade_price"]), "symbol": book["symbol"]}


@cached(HISTORY_TTL)
def lighter_xag_history(days: int = 420) -> dict[date, float]:
    end = int(datetime.now(timezone.utc).timestamp())
    data = _get(
        f"{LIGHTER}/candles",
        params={
            "market_id": LIGHTER_XAG_MARKET,
            "resolution": "1d",
            "start_timestamp": (end - days * 86400) * 1000,
            "end_timestamp": end * 1000,
            "count_back": days,
        },
    )
    return {
        datetime.fromtimestamp(c["t"] / 1000, timezone.utc).date(): float(c["c"])
        for c in data["c"]
    }


def wallex_usdt_live() -> dict:
    stats = _get(f"{WALLEX}/markets")["result"]["symbols"]["USDTTMN"]["stats"]
    return {"price": float(stats["lastPrice"]), "bid": float(stats["bidPrice"]), "ask": float(stats["askPrice"])}


@cached(HISTORY_TTL)
def wallex_usdt_history(days: int = 420) -> dict[date, float]:
    end = int(datetime.now(timezone.utc).timestamp())
    data = _get(
        f"{WALLEX}/udf/history",
        params={"symbol": "USDTTMN", "resolution": "D", "from": end - days * 86400, "to": end},
    )
    return {
        datetime.fromtimestamp(t, timezone.utc).date(): float(c)
        for t, c in zip(data["t"], data["c"])
    }


def ime_silver_live() -> dict:
    rows = _get(f"{IME_API}/CDCLiveMarket")
    row = next(r for r in rows if r.get("ContractCode") == IME_SILVER_CODE)
    return {
        "price": float(row["LastTradedPrice"]),
        "time": row.get("LastTradedPriceTime"),
        "settlement_prev": float(row.get("LastSettlementPrice") or 0),
        "settlement_prev_date": row.get("LastSettlementPricePersianDate"),
        "updated": row.get("LastUpdate"),
    }


@cached(HISTORY_TTL)
def ime_silver_history(days: int = 420) -> dict[date, dict]:
    """Daily IME silver certificate trades; the API limits each query to 6 months."""
    out: dict[date, dict] = {}
    end = tehran_today()
    start = end - timedelta(days=days)
    chunk_end = end
    while chunk_end > start:
        chunk_start = max(start, chunk_end - timedelta(days=175))
        page = 1
        while True:
            data = _post(
                f"{IME_API}/CDCTrades",
                {
                    "fromDate": chunk_start.isoformat(),
                    "toDate": chunk_end.isoformat(),
                    "pageNumber": page,
                    "pageSize": 100,
                    "customFilter": IME_SILVER_ID,
                    "sortOrder": "desc",
                },
            )
            for row in data.get("Data") or []:
                if not row.get("LastPrice"):  # holidays come back as zero-price rows
                    continue
                d = datetime.fromisoformat(row["DT"]).date()
                out[d] = {
                    "last": float(row["LastPrice"]),
                    "settlement": float(row["TodaySettlementPrice"]),
                    "persian_date": row.get("PersianDate"),
                }
            if not data.get("HasNextPage"):
                break
            page += 1
        chunk_end = chunk_start - timedelta(days=1)
    return out


def global_gram(xag_usd: float, usdt_toman: float) -> float:
    """Global price of one gram of fine silver, in rial (XAG is quoted per troy ounce of fine silver)."""
    return xag_usd / TROY_OUNCE_GRAMS * usdt_toman * 10


def ime_gram_925(ime_price: float) -> float:
    """IME certificate (1 g @ 999.9) re-expressed per gram of 925 silver, in rial."""
    return ime_price * TARGET_PURITY / IME_PURITY


def _last_on_or_before(series: dict[date, float], d: date, max_gap: int = 5):
    for back in range(max_gap + 1):
        v = series.get(d - timedelta(days=back))
        if v is not None:
            return v, d - timedelta(days=back)
    return None, None


def build_market(errors: list[str]) -> tuple[dict, list[dict]]:
    def safe(fn, label):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - one failing source must not kill the page
            errors.append(f"{label}: {describe_error(exc)}")
            return None

    with ThreadPoolExecutor(6) as pool:
        futs = {
            "xag": pool.submit(safe, lighter_xag_live, "Lighter XAG live"),
            "usdt": pool.submit(safe, wallex_usdt_live, "Wallex USDT live"),
            "ime": pool.submit(safe, ime_silver_live, "IME live"),
            "xag_h": pool.submit(safe, lighter_xag_history, "Lighter XAG history"),
            "usdt_h": pool.submit(safe, wallex_usdt_history, "Wallex USDT history"),
            "ime_h": pool.submit(safe, ime_silver_history, "IME history"),
            "tse": pool.submit(safe, tsetmc_market_state, "TSETMC market state"),
        }
        r = {k: f.result() for k, f in futs.items()}

    xag, usdt, ime = r["xag"], r["usdt"], r["ime"]
    xag_h, usdt_h, ime_h = r["xag_h"] or {}, r["usdt_h"] or {}, r["ime_h"] or {}

    # Before today's IME session trades, the live board reports 0: show the last trade of the
    # latest trading day instead, flagged so the page can say which day it is from.
    if ime and not ime["price"] and ime_h:
        d = max(ime_h)
        ime.update(price=ime_h[d]["last"], stale=True, stale_date=d.isoformat(),
                   stale_persian_date=ime_h[d]["persian_date"])
    if ime and not ime["price"]:
        errors.append("IME live: no trade yet today and no IME history to fall back on")
        ime = None
    market = {"xag": xag, "usdt": usdt, "ime": ime, "tse": r["tse"]}
    if xag and usdt:
        market["global_gram"] = global_gram(xag["price"], usdt["price"])
    if ime:
        market["ime_925"] = ime_gram_925(ime["price"])
    if market.get("global_gram") and ime:
        market["ime_bubble"] = (ime["price"] / market["global_gram"] - 1) * 100

    history = []
    for d in sorted(ime_h):
        xv, xd = _last_on_or_before(xag_h, d)
        uv, ud = _last_on_or_before(usdt_h, d)
        if xv is None or uv is None:
            continue
        g = global_gram(xv, uv)
        i = ime_h[d]["last"]
        history.append({
            "date": d.isoformat(),
            "persian_date": ime_h[d]["persian_date"],
            "ime_raw": ime_h[d]["last"],
            "xag": xv,
            "usdt": uv,
            "global_gram": g,
            "bubble": (i / g - 1) * 100,
        })
    today = tehran_today().isoformat()
    if market.get("ime_bubble") is not None and not ime.get("stale"):
        live = {
            "date": today, "persian_date": "live", "ime_raw": ime["price"],
            "xag": xag["price"], "usdt": usdt["price"], "global_gram": market["global_gram"],
            "bubble": market["ime_bubble"], "live": True,
        }
        history = [h for h in history if h["date"] != today] + [live]

    market["ime_history"] = {d.isoformat(): v["last"] for d, v in ime_h.items()}
    return market, history


# --------------------------------------------------------------------------
# Funds: symbols (Fundbase) -> regNo (Fipiran) / insCode (TSETMC)
# --------------------------------------------------------------------------

def load_symbols() -> list[str]:
    return json.loads((ROOT / "funds.json").read_text(encoding="utf-8"))["symbols"]


def load_website_overrides() -> dict[str, str]:
    """Optional {"symbol": "https://fund-site"} map in funds.json, used instead of Fipiran's address."""
    return json.loads((ROOT / "funds.json").read_text(encoding="utf-8")).get("websites", {})


def describe_error(exc: Exception) -> str:
    """Short, readable reason for a failed request."""
    text = str(exc)
    if isinstance(exc, requests.exceptions.SSLError) or "CERTIFICATE_VERIFY_FAILED" in text:
        return "site's TLS certificate is invalid for its address"
    if "NameResolutionError" in text or "Failed to resolve" in text:
        return "domain does not resolve (site offline or moved)"
    if isinstance(exc, requests.exceptions.Timeout):
        return "timed out (temporary; will retry within 15 minutes)"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "connection refused or dropped"
    if isinstance(exc, requests.exceptions.HTTPError):
        return f"HTTP {exc.response.status_code}"
    if isinstance(exc, ValueError):
        return "unexpected response format"
    return text[:120]


@cached(24 * 3600)
def fipiran_fund_index() -> dict[str, dict]:
    data = _post(f"{FIPIRAN}/fund/fundcompare/", {"regNos": [], "showMarketMakers": False}, timeout=90)
    return {normalize_fa(f.get("smallSymbolName")): f for f in data["items"] if f.get("smallSymbolName")}


@cached(24 * 3600)
def tsetmc_search(symbol: str) -> dict | None:
    data = _get(f"{TSETMC}/Instrument/GetInstrumentSearch/{urllib.parse.quote(symbol)}")
    for item in data.get("instrumentSearch") or []:
        if normalize_fa(item["lVal18AFC"]) == symbol:
            return item
    return None


# TSETMC market state titles -> English (the code letters are undocumented, so the title is used).
MARKET_STATES = {"باز": "Open", "بسته": "Closed", "پیش گشایش": "Pre-opening", "تعطیل": "Closed"}


def tsetmc_market_state() -> dict:
    """Whether the stock market is open now, and the date of its latest trading session."""
    o = _get(f"{TSETMC}/MarketData/GetMarketOverview/1")["marketOverview"]
    title = normalize_fa(o.get("marketStateTitle"))
    return {
        "code": (o.get("marketState") or "").strip(),
        "title": title,
        "label": MARKET_STATES.get(title, title or "Unknown"),
        "session_date": _deven_iso(o.get("marketActivityDEven")),
        "session_time": o.get("marketActivityHEven"),
    }


def fund_live(ins: str) -> dict:
    info = _get(f"{TSETMC}/ClosingPrice/GetClosingPriceInfo/{ins}")["closingPriceInfo"]
    etf = _get(f"{TSETMC}/Fund/GetETFByInsCode/{ins}").get("etf") or {}
    state = info.get("instrumentState") or {}
    return {
        # "A" (مجاز) = open for trading; anything else (e.g. ممنوع-متوقف) means the symbol is halted.
        "state": (state.get("cEtaval") or "").strip(),
        "state_title": normalize_fa(state.get("cEtavalTitle")),
        "last": float(info["pDrCotVal"]),
        "closing": float(info["pClosing"]),
        "deven": info.get("finalLastDate") or info.get("dEven"),
        "heven": info.get("hEven"),
        "nav": float(etf.get("pRedTran") or 0) or None,
        "nav_deven": etf.get("deven"),
        "nav_heven": etf.get("hEven"),
    }


@cached(HISTORY_TTL)
def fund_price_history(ins: str) -> dict[date, float]:
    rows = _get(f"{TSETMC}/ClosingPrice/GetClosingPriceDailyList/{ins}/0")["closingPriceDaily"]
    return {deven_to_date(r["dEven"]): float(r["pDrCotVal"]) for r in rows if r.get("zTotTran", 0) > 0}


@cached(HISTORY_TTL)
def fund_nav_history(reg_no: str, group_id) -> dict[date, float]:
    """Daily redemption NAV from Fipiran.

    Multi-class commodity funds list silver as its own groupId; single-class funds
    only answer on groupId=0, so try the fund's group first and fall back to 0.
    """
    for gid in dict.fromkeys([group_id or 0, 0]):
        for _ in range(3):
            try:
                rows = _get(f"{FIPIRAN}/chart/getfundchart",
                            params={"regno": reg_no, "groupId": gid, "showAll": "true"}, timeout=60)
                break
            except ValueError:  # Fipiran intermittently answers with an empty body
                time.sleep(1.5)
        else:
            rows = []
        if rows:
            return {datetime.fromisoformat(r["date"]).date(): float(r["cancelNav"]) for r in rows if r.get("cancelNav")}
    return {}


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> date:
    jy += 1595
    days = -355668 + 365 * jy + (jy // 33) * 8 + ((jy % 33) + 3) // 4 + jd
    days += (jm - 1) * 31 if jm < 7 else (jm - 7) * 30 + 186
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    leap = (gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0
    month_days = [0, 31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 1
    while gm <= 12 and gd > month_days[gm]:
        gd -= month_days[gm]
        gm += 1
    return date(gy, gm, gd)


def gregorian_to_jalali(d: date) -> str:
    g_days = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = d.year + 1 if d.month > 2 else d.year
    days = (355666 + 365 * d.year + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400
            + d.day + g_days[d.month - 1])
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    jm, jd = (1 + days // 31, 1 + days % 31) if days < 186 else (7 + (days - 186) // 30, 1 + (days - 186) % 30)
    return f"{jy:04d}/{jm:02d}/{jd:02d}"


_dns_pool = ThreadPoolExecutor(4, thread_name_prefix="dns")


def _resolve_quickly(host: str, timeout: float = 10.0) -> None:
    """Bound the DNS lookup, which the request timeout doesn't cover and can hang ~15 s.

    A domain that really doesn't exist fails at once; a slow lookup is reported as temporary.
    """
    try:
        _dns_pool.submit(socket.getaddrinfo, host, 443).result(timeout=timeout)
    except socket.gaierror as exc:
        raise requests.exceptions.ConnectionError(f"Failed to resolve '{host}'") from exc
    except TimeoutError as exc:
        raise requests.exceptions.Timeout(f"DNS lookup for '{host}' timed out") from exc


def _site_root(website: str) -> str:
    return website if website.startswith("http") else f"https://{website}"


@cached(HISTORY_TTL)
def website_nav_history(website: str, symbol: str, ins: str) -> tuple[dict[date, float], str]:
    """Redemption NAV history from the fund's own website.

    Supports the two platforms almost every silver ETF runs on:
    Rayan Hamafza (/api/v1/public/navPerShare/{fundId}) and
    Tadbir (/Chart/TotalNAV?type=getnavtotal&basketId=N).
    """
    root, html, last_exc = None, None, None
    base = _site_root(website)
    variants = [base]
    if "://www." not in base:
        variants.append(base.replace("://", "://www.", 1))
    for candidate in variants:
        try:
            _resolve_quickly(urllib.parse.urlparse(candidate).hostname)
            html = _session.get(candidate, timeout=20).text
            root = candidate
            break
        except requests.RequestException as exc:
            last_exc = exc
    if html is None:
        raise last_exc
    if "/assets/fund.js" in html or "Rayanhamafza" in html:
        fund_id = 1
        try:
            for item in _get(f"{root}/api/v1/public/fundItems"):
                if ins and ins in (item.get("tsetmcUrl") or ""):
                    fund_id = item["fundId"]
        except (requests.RequestException, ValueError):
            pass
        url = f"{root}/api/v1/public/navPerShare/{fund_id}"
        rows = _get(url)
        out = {}
        for r in rows:
            y, m, d = (int(x) for x in r["jalaliDate"].split("/"))
            if r.get("sellNAVPerShare"):
                out[jalali_to_gregorian(y, m, d)] = float(r["sellNAVPerShare"])
        return out, url
    if "/Chart/TotalNAV" in html:
        basket = 1
        for value, label in re.findall(r'<option value="(\d+)">([^<]+)', html):
            if f"({symbol})" in normalize_fa(label).replace(" ", ""):
                basket = int(value)
        url = f"{root}/Chart/TotalNAV?type=getnavtotal&basketId={basket}"
        series = _get(url)
        cancel = next((s for s in series if normalize_fa(s.get("name")) == "ابطال"), None)
        out = {}
        for p in (cancel or {}).get("List") or []:
            mm, dd, yy = (int(x) for x in p["x"].split("/"))
            out[date(yy, mm, dd)] = float(p["y"])
        return out, url
    raise ValueError("unrecognised fund website platform")


def build_fund(symbol: str, meta: dict, ime_hist: dict[str, float], today: date,
               stored: dict[str, tuple[float, str]]) -> dict:
    row: dict = {"symbol": symbol, "name": meta.get("name"), "insCode": meta.get("insCode"),
                 "regNo": meta.get("regNo"), "website": meta.get("website"), "errors": []}
    ins, reg = meta.get("insCode"), meta.get("regNo")
    try:
        live = fund_live(ins)
        row.update(live_price=live)
    except Exception as exc:  # noqa: BLE001
        row["errors"].append(f"TSETMC live: {describe_error(exc)}")
        live = None
    prices, navs = {}, {}
    try:
        prices = fund_price_history(ins)
    except Exception as exc:  # noqa: BLE001
        row["errors"].append(f"TSETMC history: {describe_error(exc)}")
    # NAV history: fund website first (exact unit class), Fipiran fills any gaps.
    # nav_from records which source supplied each day, so the page can say where the average came from.
    row["nav_history_sources"] = []
    nav_from: dict[date, str] = {}
    origins: dict[str, dict] = {}
    if meta.get("website"):
        try:
            site_navs, url = website_nav_history(meta["website"], symbol, ins)
            if site_navs:
                navs.update(site_navs)
                nav_from.update(dict.fromkeys(site_navs, "website"))
                origins["website"] = {"url": url, "host": urllib.parse.urlparse(url).hostname}
                row["nav_history_sources"].append(url)
        except Exception as exc:  # noqa: BLE001
            row["errors"].append(f"Fund website ({meta['website']}): {describe_error(exc)}")
    if reg:
        try:
            fip = fund_nav_history(reg, meta.get("groupId"))
            # Fipiran can return another unit class's NAV for multi-class funds; keep plausible days only.
            added = {d: v for d, v in fip.items() if d not in navs and d in prices and 0.5 < prices[d] / v < 1.5}
            if added:
                navs.update(added)
                nav_from.update(dict.fromkeys(added, "fipiran"))
                origins["fipiran"] = {"url": f"{FIPIRAN}/chart/getfundchart?regno={reg}"}
                row["nav_history_sources"].append(f"{FIPIRAN}/chart/getfundchart?regno={reg}")
        except Exception as exc:  # noqa: BLE001
            row["errors"].append(f"Fipiran NAV history: {describe_error(exc)}")
    # NAVs recorded in the daily table fill the days the sources above don't cover.
    for key, label in (("store", "daily table (data/daily.csv)"), ("fundbase", "Fundbase bubble history (imported into data/daily.csv)")):
        added = {date.fromisoformat(d): v for d, (v, k) in stored.items()
                 if k == key and date.fromisoformat(d) < today and date.fromisoformat(d) not in navs}
        if added:
            navs.update(added)
            nav_from.update(dict.fromkeys(added, key))
            row["nav_history_sources"].append(label)

    last = live["last"] if live else None
    nav = live["nav"] if live and live["nav"] else None
    nav_source = "tsetmc"
    if nav is None and navs:
        nav_date = max(navs)
        nav, nav_source = navs[nav_date], f"history {nav_date.isoformat()}"
    row.update(last=last, nav=nav, nav_source=nav_source)
    # None when TSETMC history failed, so a fetch error never hides a fund.
    row["trading_days"] = len(prices) if prices else None
    row["bubble"] = (last / nav - 1) * 100 if last and nav else None

    # Daily bubble: last traded price of the day vs. that day's redemption NAV.
    daily = []
    for d in sorted(prices):
        if d >= today:
            continue
        n = navs.get(d)
        if n:
            daily.append({"date": d.isoformat(), "value": (prices[d] / n - 1) * 100, "price": prices[d], "nav": n})
    prev = daily[-AVG_WINDOW:]
    row["avg_window"] = {"n": len(prev), "from": prev[0]["date"] if prev else None, "to": prev[-1]["date"] if prev else None}
    counts: dict[str, int] = {}
    for p in prev:
        k = nav_from[date.fromisoformat(p["date"])]
        counts[k] = counts.get(k, 0) + 1
    row["avg_nav_origins"] = [{"key": k, "days": n, **origins.get(k, {})}
                              for k, n in sorted(counts.items(), key=lambda kv: -kv[1])]
    row["avg_bubble"] = sum(p["value"] for p in prev) / len(prev) if prev else None
    row["deviation"] = row["bubble"] - row["avg_bubble"] if row["bubble"] is not None and row["avg_bubble"] is not None else None
    trend = [{"date": p["date"], "value": p["value"]} for p in daily]
    if row["bubble"] is not None:
        trend.append({"date": today.isoformat(), "value": row["bubble"]})
    row["trend"] = trend[-AVG_WINDOW:]

    # SF ratio: P80 of (IME 925 gram price / fund last price) over the last 200 trading days.
    ratios = []
    for d in sorted(prices):
        ime = ime_hist.get(d.isoformat())
        if ime and prices[d]:
            ratios.append({"date": d.isoformat(), "ratio": ime_gram_925(ime) / prices[d]})
    window = ratios[-SF_WINDOW:]
    row["sf_window"] = {"n": len(window), "from": window[0]["date"] if window else None,
                        "to": window[-1]["date"] if window else None,
                        "min": min((w["ratio"] for w in window), default=None),
                        "max": max((w["ratio"] for w in window), default=None)}
    row["sf"] = round(percentile([w["ratio"] for w in window], SF_PERCENTILE)) if window else None
    row["eq_silver"] = row["sf"] * last if row["sf"] and last else None
    return row


def build_funds(market: dict, errors: list[str]) -> list[dict]:
    symbols = load_symbols()
    try:
        index = fipiran_fund_index()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Fipiran fund list: {describe_error(exc)}")
        index = {}

    overrides = load_website_overrides()

    def resolve(sym):
        f = index.get(sym)
        meta = {"name": f.get("name") if f else None, "regNo": f.get("regNo") if f else None, "groupId": f.get("groupId") if f else None,
                "insCode": f.get("insCode") if f else None,
                "website": overrides.get(sym) or ((f.get("websiteAddress") or [None])[0] if f else None)}
        # TSETMC's lVal30 is the display name the gold dashboard uses (e.g. "صندوق س.کالای آشنا").
        try:
            hit = tsetmc_search(sym)
        except requests.RequestException:
            hit = None
        if hit:
            meta["insCode"] = meta["insCode"] or hit["insCode"]
            meta["name"] = normalize_fa(hit["lVal30"])
        return meta

    today = tehran_today()
    ime_hist = market.get("ime_history") or {}
    store = table_navs()
    with ThreadPoolExecutor(8) as pool:
        metas = list(pool.map(resolve, symbols))
        rows = list(pool.map(lambda sm: build_fund(sm[0], sm[1], ime_hist, today, store.get(sm[0], {})),
                             zip(symbols, metas)))
    for r in rows:
        errors.extend(f"{r['symbol']} · {e}" for e in r["errors"])
        r["name"] = normalize_fa(r["name"]).split("(")[0].strip()
    return rows


def build_snapshot() -> dict:
    errors: list[str] = []
    market, history = build_market(errors)
    funds = build_funds(market, errors)
    snap = {
        "fetched_at": tehran_now().strftime("%Y-%m-%d %H:%M:%S"),
        "market": market,
        "bubble_history": history,
        "funds": funds,
        "errors": errors,
    }
    body = json.dumps(snap, ensure_ascii=False)
    LIVE_PATH.parent.mkdir(exist_ok=True)
    tmp = LIVE_PATH.with_suffix(".tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(LIVE_PATH)  # atomic, so the page never reads a half-written file
    save_daily_row(snap)
    return snap


# Columns of data/daily.csv: the day and market first, then four per fund ("<symbol>_status", ...).
TABLE_COLUMNS = ["date", "jalali", "weekday", "day_status", "tsetmc_session_date", "ime_traded",
                 "xag_usd", "usdt_irr", "global_gram_irr", "ime_irr", "ime_trade_date", "ime_premium_pct",
                 "first_fetch", "last_fetch"]
FUND_COLUMNS = ["status", "last", "nav", "bubble_pct"]
IMPORTED_DAY = "imported: NAV from Fundbase bubble history"  # rows added before recording started


def load_table() -> list[dict]:
    try:
        with TABLE_PATH.open(encoding="utf-8-sig", newline="") as fh:
            return list(csv.DictReader(fh))
    except OSError:
        return []


def table_navs() -> dict[str, dict[str, tuple[float, str]]]:
    """{symbol: {iso date: (nav, "store" | "fundbase")}} from the NAV columns of the daily table."""
    out: dict[str, dict[str, tuple[float, str]]] = {}
    for row in load_table():
        key = "fundbase" if row.get("day_status") == IMPORTED_DAY else "store"
        for col, v in row.items():
            if col and col.endswith("_nav") and v:
                out.setdefault(col[:-4], {})[row["date"]] = (float(v), key)
    return out


def save_table(rows: dict[str, dict], symbols: list[str]) -> None:
    extra = [c for r in rows.values() for c in r if c not in TABLE_COLUMNS]
    columns = TABLE_COLUMNS + [f"{s}_{c}" for s in symbols for c in FUND_COLUMNS]
    columns += [c for c in dict.fromkeys(extra) if c not in columns]  # funds removed from funds.json keep their columns
    TABLE_PATH.parent.mkdir(exist_ok=True)
    tmp = TABLE_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:  # BOM so Excel reads the Persian symbols
        w = csv.DictWriter(fh, fieldnames=columns, restval="")
        w.writeheader()
        w.writerows(rows[d] for d in sorted(rows))
    tmp.replace(TABLE_PATH)


def _deven_iso(deven) -> str | None:
    return deven_to_date(deven).isoformat() if deven else None


def _cell(v, digits: int | None = None):
    return "" if v is None else round(v) if digits is None else round(v, digits)


def save_daily_row(snap: dict) -> None:
    """Adds or updates today's row in data/daily.csv: key prices, and whether the market and each fund traded.

    A day on which nothing traded (weekend, holiday) still gets a row that says so. Each fund's NAV is
    written to the row of the day TSETMC published it, so a holiday never gets the previous day's NAV."""
    today = tehran_today().isoformat()
    rows = {r["date"]: r for r in load_table()}
    prev = rows.get(today, {})
    m = snap["market"]
    ime = m.get("ime") or {}
    usdt = (m.get("usdt") or {}).get("price")
    ime_traded = bool(ime) and not ime.get("stale")
    row = dict(prev)
    funds = {}
    for f in snap["funds"]:
        lp = f.get("live_price") or {}
        trade_date = _deven_iso(lp.get("deven"))
        traded = trade_date == today if trade_date else None
        halted = (lp.get("state") or "A") != "A"
        funds[f["symbol"]] = (f, traded, halted, _deven_iso(lp.get("nav_deven")) if f.get("nav_source") == "tsetmc" else None)
    tse_traded = any(t for _, t, _, _ in funds.values())
    for sym, (f, traded, halted, nav_date) in funds.items():
        row[f"{sym}_status"] = ("traded" if traded else "unknown" if traded is None else "halted" if halted
                                else "no trade" if tse_traded else "market closed")
        row[f"{sym}_last"] = _cell(f.get("last"))
        row[f"{sym}_bubble_pct"] = _cell(f.get("bubble"), 3)
        if f.get("nav") and nav_date:
            target = row if nav_date == today else rows.get(nav_date)
            if target is not None:
                target[f"{sym}_nav"] = _cell(f["nav"])
    trading = tse_traded or ime_traded or prev.get("day_status") == "trading day"  # never downgrade a day that had trades
    row.update({
        "date": today,
        "jalali": gregorian_to_jalali(date.fromisoformat(today)),
        "weekday": date.fromisoformat(today).strftime("%A"),
        "day_status": "trading day" if trading else "no trading (weekend or holiday)",
        "tsetmc_session_date": (m.get("tse") or {}).get("session_date") or "",
        "ime_traded": "yes" if ime_traded else "no",
        "xag_usd": _cell((m.get("xag") or {}).get("price"), 4),
        "usdt_irr": _cell(usdt * 10 if usdt else None),
        "global_gram_irr": _cell(m.get("global_gram")),
        "ime_irr": _cell(ime.get("price")),
        "ime_trade_date": today if ime_traded else ime.get("stale_date") or "",
        "ime_premium_pct": _cell(m.get("ime_bubble"), 3),
        "first_fetch": prev.get("first_fetch") or snap["fetched_at"],
        "last_fetch": snap["fetched_at"],
    })
    rows[today] = row
    save_table(rows, list(funds))


def load_saved_snapshot() -> dict | None:
    try:
        return json.loads(LIVE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


if __name__ == "__main__":
    s = build_snapshot()
    m = s["market"]
    print("XAG", m.get("xag"), "USDT", m.get("usdt"), "IME", m.get("ime"))
    print("global gram", m.get("global_gram"), "ime925", m.get("ime_925"), "bubble", m.get("ime_bubble"))
    print("history points", len(s["bubble_history"]))
    for f in s["funds"]:
        print(f["symbol"], f["last"], f["nav"], f["bubble"] and round(f["bubble"], 2),
              f["avg_bubble"] and round(f["avg_bubble"], 2), f["avg_window"]["n"], f["sf"], f["sf_window"]["n"], f["eq_silver"])
    print("errors", s["errors"])
