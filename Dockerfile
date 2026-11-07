# One image serving both dashboards (gold and silver) on port 8501, e.g. on darkube.
FROM python:3.12-slim

ENV TZ=Asia/Tehran \
    PYTHONUNBUFFERED=1 \
    SNAPSHOT_FROM_COLLECTOR=1 \
    STREAMLIT_SERVER_FILE_WATCHER_TYPE=none

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# The shipped silver daily table is kept aside so a persistent disk mounted on /app/silver/data
# starts with it; files already on the disk are never overwritten.
RUN cp -r silver/data silver/seed-data

EXPOSE 8501
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=5)" || exit 1

# silver/collector.py fetches silver data every 10 seconds (even with nobody viewing) and writes
# silver/data/daily.csv and static/live.json; the silver page only reads what it saved
# (SNAPSHOT_FROM_COLLECTOR=1). The gold page fetches from TSETMC when Refresh is pressed.
CMD ["sh", "-c", "mkdir -p silver/data && cp -rn silver/seed-data/. silver/data/ ; python silver/collector.py & exec streamlit run app.py --server.port=8501 --server.address=0.0.0.0"]
