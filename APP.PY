import streamlit as st
import pandas as pd
import requests
import plotly.express as px
from datetime import datetime

st.set_page_config(
    page_title="World City Populations",
    layout="wide",
    initial_sidebar_state="collapsed"
)

DATA_URL = "https://worldpopulationreview.com/static/cities.json"

@st.cache_data(ttl=3600)  # refresh every hour
def load_data():
    r = requests.get(DATA_URL, timeout=10)
    r.raise_for_status()
    data = r.json()
    df = pd.DataFrame(data)
    df = df.rename(columns={
        "name": "City",
        "country": "Country",
        "population": "Population"
    })
    df["Population"] = df["Population"].astype(int)
    df = df.sort_values("Population", ascending=False)
    return df.head(100)

df = load_data()

# ---------- HEADER ----------
st.markdown(
    """
    <h1 style="text-align:center;">🌍 Top 100 Most Populated Cities</h1>
    <p style="text-align:center; color: #94a3b8;">
    Auto-updated population estimates • Source: World Population Review
    </p>
    """,
    unsafe_allow_html=True
)

# ---------- METRICS ----------
c1, c2, c3 = st.columns(3)
c1.metric("Cities Tracked", "100")
c2.metric("Largest City", df.iloc[0]["City"])
c3.metric("Last Update", datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))

st.divider()

# ---------- SEARCH ----------
search = st.text_input("Search city or country", "")

if search:
    filtered = df[
        df["City"].str.contains(search, case=False) |
        df["Country"].str.contains(search, case=False)
    ]
else:
    filtered = df

# ---------- TABLE ----------
st.dataframe(
    filtered.style.format({"Population": "{:,}"}),
    use_container_width=True,
    height=600
)

# ---------- CHART ----------
fig = px.bar(
    filtered.head(20),
    x="Population",
    y="City",
    orientation="h",
    color="Population",
    color_continuous_scale="Viridis",
    title="Top 20 Cities by Population"
)

fig.update_layout(
    height=700,
    yaxis=dict(autorange="reversed"),
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)"
)

st.plotly_chart(fig, use_container_width=True)

# ---------- FOOTER ----------
st.caption(
    "Population figures are estimates, auto-refreshed hourly. "
    "True real-time city population tracking does not exist."
)
