"""NAV bubble dashboards for Iranian gold and silver funds, served as one Streamlit app.

    streamlit run app.py

A toggle at the top switches between the two dashboards. Gold is the home page (/),
silver is at /silver. Each dashboard lives in its own folder (gold/, silver/).
"""

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent

# Each dashboard imports its own data module (gold/tsetmc_data.py, silver/silver_data.py).
for folder in ("gold", "silver"):
    path = str(ROOT / folder)
    if path not in sys.path:
        sys.path.insert(0, path)

st.set_page_config(page_title="NAV Bubble Dashboard", layout="wide")

GOLD = st.Page(ROOT / "gold" / "dashboard.py", title="طلا", icon="🟡", default=True)
SILVER = st.Page(ROOT / "silver" / "dashboard.py", title="نقره", icon="🥈", url_path="silver")
PAGES = {"gold": GOLD, "silver": SILVER}
LABELS = {"gold": "🟡 طلا", "silver": "🥈 نقره"}

# The built-in navigation menu is hidden; the toggle below replaces it.
page = st.navigation(list(PAGES.values()), position="hidden")
current = "silver" if page.title == SILVER.title else "gold"

st.markdown(
    """
<style>
@font-face { font-family: "Vazirmatn"; src: url("app/static/fonts/Vazirmatn.woff2") format("woff2"); font-weight: 100 900; font-display: swap; }
.st-key-metal-switch { align-items: center; }
.st-key-metal-switch button { font-family: 'Vazirmatn', Tahoma, sans-serif; min-width: 6.5rem; }
</style>
""",
    unsafe_allow_html=True,
)


def remember_choice() -> None:
    # Runs when the toggle is clicked, before the script reruns.
    st.session_state["metal_target"] = st.session_state["metal"]


target = st.session_state.pop("metal_target", None)
if target and target != current:
    st.switch_page(PAGES[target])

# The toggle always shows the page being viewed (also after the browser's back button or a direct link).
st.session_state["metal"] = current
with st.container(key="metal-switch"):
    st.segmented_control(
        "Metal", list(PAGES), format_func=LABELS.get, key="metal", required=True,
        on_change=remember_choice, label_visibility="collapsed",
    )

page.run()
