# Silver Funds NAV Bubble Dashboard

A live dashboard of the NAV bubble of Iranian silver commodity funds, and of the IME silver certificate premium over the global silver price. Data refreshes every 10 seconds. Click any number to see its formula, inputs and source.

It is one of the two pages of the app in the repository root (the other is gold). For running and deploying, see the [main README](../README.md).

## Stored data

All data is kept in a single table, **`silver/data/daily.csv`**, with one row per calendar day. Today's row is updated on every fetch, so its final values are the end-of-day record.

- **Day columns:** date (Gregorian and Jalali), `day_status` (`trading day` or `no trading (weekend or holiday)`), whether IME traded, global silver price, USDT rate, IME certificate price and premium.
- **Four columns per fund:** `<symbol>_status` (`traded`, `no trade`, `halted`, `market closed`), `_last`, `_nav` and `_bubble_pct`.
- **NAV:** each NAV goes in the row of the day TSETMC published it. These NAV columns also serve as the dashboard's own NAV history for the 50-day average.
- Rows marked `imported: NAV from Fundbase bubble history` hold earlier NAVs for three funds that have no other source.

The file opens directly in Excel. `static/live.json` (in the repository root) holds only the latest snapshot for the open page, and it is overwritten on every fetch.

On the server, mount a persistent disk at `/app/silver/data`. Without it, the rows collected since the last deploy are lost on every restart.

## Files

| File | Purpose |
|---|---|
| `dashboard.py` | Streamlit page (top bar, CSV download) |
| `dashboard.html` | User interface: cards, chart, table and explainer boxes |
| `silver_data.py` | Data fetching and calculations |
| `collector.py` | Continuous data collection on the server |
| `funds.json` | List of funds. Edit it to add or remove a symbol. |
| `../static/fonts/` | Vazirmatn font (OFL license) |

**Data sources:** TSETMC, IME, Lighter (XAG), Wallex (USDT), Fipiran, Fundbase, and the funds' own websites.
