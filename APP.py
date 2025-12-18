import io
import zipfile
import requests
import pandas as pd
import streamlit as st
from datetime import datetime
import plotly.express as px


WPR_URL = "https://worldpopulationreview.com/static/cities.json"
GEONAMES_URL = "https://download.geonames.org/export/dump/cities15000.zip"  # public + stable

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CityPopApp/1.0; +https://streamlit.io)",
    "Accept": "application/json,text/plain,*/*",
}

@st.cache_data(ttl=3600)
def load_data(top_n: int = 100) -> pd.DataFrame:
    # --- Primary: WorldPopulationReview (frequent updates, but can block bots) ---
    try:
        r = requests.get(WPR_URL, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            df = pd.DataFrame(r.json())
            df = df.rename(columns={"name": "City", "country": "Country", "population": "Population"})
            df["Population"] = pd.to_numeric(df["Population"], errors="coerce").fillna(0).astype("int64")
            df = df.sort_values("Population", ascending=False).head(top_n)
            df["Source"] = "WorldPopulationReview"
            return df.reset_index(drop=True)
        else:
            # Don’t crash; fall through to GeoNames
            st.warning(f"WPR fetch failed (HTTP {r.status_code}). Falling back to GeoNames.")
    except Exception as e:
        st.warning(f"WPR fetch failed ({type(e).__name__}). Falling back to GeoNames.")

    # --- Fallback: GeoNames (stable, updated periodically; city populations are estimates) ---
    r = requests.get(GEONAMES_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()

    z = zipfile.ZipFile(io.BytesIO(r.content))
    # cities15000.txt inside zip
    with z.open("cities15000.txt") as f:
        cols = [
            "geonameid","name","asciiname","alternatenames","latitude","longitude","feature_class",
            "feature_code","country_code","cc2","admin1_code","admin2_code","admin3_code","admin4_code",
            "population","elevation","dem","timezone","modification_date"
        ]
        gdf = pd.read_csv(f, sep="\t", header=None, names=cols, dtype={"population": "int64"}, low_memory=False)

    df = gdf.rename(columns={"name": "City", "country_code": "Country", "population": "Population"})
    df = df[["City", "Country", "Population"]].sort_values("Population", ascending=False).head(top_n)
    df["Source"] = "GeoNames (cities15000)"
    return df.reset_index(drop=True)

# ---------- LOAD DATA ----------
try:
    df = load_data(top_n=100)
except Exception:
    st.error("Failed to load city population data.")
    st.stop()

if df is None or df.empty:
    st.error("No population data available.")
    st.stop()

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
c1.metric("Cities Tracked", f"{len(df):,}")
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

