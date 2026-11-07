# NAV Bubble Dashboard

Live NAV-bubble dashboards for Iranian commodity funds, served as one Streamlit app:

- **Gold** (`gold/`): NAV bubble, 50-day average and deviation, GF ratio and EqGold price of the gold funds. Data comes from TSETMC when **Refresh** is pressed.
- **Silver** (`silver/`): NAV bubble of the silver funds and the IME silver certificate premium over the global silver price. Data refreshes every 10 seconds. See [`silver/README.md`](silver/README.md).

A **طلا / نقره** toggle at the top switches between them. Gold is the home page (`/`), silver is at `/silver`.

**Requirements:** Python 3.11 or later, and an internet connection.

## Running locally

### macOS
Double-click `run.command`. The first run installs the dependencies, which takes about a minute. The dashboard then opens in your browser at `http://localhost:8501`. Keep the Terminal window open while you use it.

> If macOS blocks the file, right-click `run.command`, choose **Open**, then click **Open** again.

### Windows and Linux
From the project folder:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m streamlit run app.py
```

On Windows, use `.venv\Scripts\` instead of `.venv/bin/`.

Always start the app from the project folder with `app.py`: the silver page's live updates are served from the `static/` folder next to it.

## Deploying (Docker / darkube)

The `Dockerfile` builds one image for both dashboards. In the container, `silver/collector.py` runs next to the app and saves silver data every 10 seconds, even when no one has the page open.

```bash
docker build -t nav-bubble-dashboard .
docker run -d -p 8501:8501 -v "$PWD/silver-data:/app/silver/data" nav-bubble-dashboard
```

On darkube (app `navbubbledashboard`, domain `navbubbledashboard.darkube.ir`):
1. The app builds from this repository's `Dockerfile`, and every push to `main` deploys automatically.
2. The service port is `8501`.
3. Mount a **persistent disk** at `/app/silver/data`. On first start it is filled with the shipped `silver/data/daily.csv`. Files already on the disk are never overwritten.
4. **500 MB RAM** or more is recommended: the app runs Streamlit and the silver collector side by side.

> ⚠️ `silver/data/daily.csv` is the silver dashboard's only stored history. Without a persistent disk, the rows collected since the last deploy are lost on every restart or redeploy.

## Project structure

| Path | Purpose |
|---|---|
| `app.py` | Entry point: the طلا / نقره toggle and page routing |
| `gold/dashboard.py` | Gold dashboard page |
| `gold/tsetmc_data.py` | Gold data fetching from TSETMC |
| `gold/data/` | Gold snapshots, history and gold-to-fund conversion ratios |
| `silver/dashboard.py` | Silver dashboard page (top bar, CSV download) |
| `silver/dashboard.html` | Silver user interface: cards, chart, table and explainer boxes |
| `silver/silver_data.py` | Silver data fetching and calculations |
| `silver/collector.py` | Continuous silver data collection on the server |
| `silver/funds.json` | List of silver funds. Edit it to add or remove a symbol. |
| `silver/data/daily.csv` | Silver daily table |
| `static/` | Files served to the browser: the Vazirmatn font and the silver page's `live.json` |
| `.streamlit/config.toml` | Streamlit settings (dark theme, static file serving) |
| `run.command`, `make-zip.command` | Run the app and build a zip to share on macOS |
| `Dockerfile` | Server image |

To run the gold tests: `cd gold && python -m unittest`.
