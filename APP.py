import io
import zipfile
from datetime import datetime

import requests
import pandas as pd
import streamlit as st
import plotly.express as px

st.set_page_config(
    page_title="World City Populations",
    layout="wide",
    initial_sidebar_state="collapsed",
)

WPR_URL = "https://worldpopulationreview.com/static/cities.json"
GEONAMES_URL = "https://download.geonames.org/export/dump/cities15000.zip"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CityPopApp/1.0; +https://streamlit.io)",
    "Accept": "application/json,text/plain,*/*",
}


@st.cache_data(ttl=3600)
def load_data(top_n: int = 100) -> pd.DataFrame:
    # ---------- PRIMARY: WorldPopulationReview ----------
    try:
        r = requests.get(WPR_URL, headers=HEADERS, timeout=15)
        r.raise_for_status()

        df = pd.DataFrame(r.json())
        df = df.rename(
            columns={
                "name": "City",
                "country": "Country",
                "population": "Population",
                "lat": "Latitude",
                "lng": "Longitude",
                "latitude": "Latitude",
                "longitude": "Longitude",
            }
        )

        df["Population"] = pd.to_numeric(df["Population"], errors="coerce").fillna(0).astype("int64")
        df["Latitude"] = pd.to_numeric(df.get("Latitude"), errors="coerce")
        df["Longitude"] = pd.to_numeric(df.get("Longitude"), errors="coerce")

        df = df.sort_values("Population", ascending=False).head(top_n)
        df["Source"] = "WorldPopulationReview"
        return df.reset_index(drop=True)

    except Exception:
        # fall back cleanly
        pass

    # ---------- FALLBACK: GeoNames ----------
    r = requests.get(GEONAMES_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()

    z = zipfile.ZipFile(io.BytesIO(r.content))
    with z.open("cities15000.txt") as f:
        cols = [
            "geonameid", "name", "asciiname", "alternatenames", "latitude", "longitude",
            "feature_class", "feature_code", "country_code", "cc2", "admin1_code",
            "admin2_code", "admin3_code", "admin4_code", "population", "elevation",
            "dem", "timezone", "modification_date",
        ]
        gdf = pd.read_csv(f, sep="\t", header=None, names=cols, low_memory=False)

    df = gdf.rename(
        columns={
            "name": "City",
            "country_code": "Country",
            "population": "Population",
            "latitude": "Latitude",
            "longitude": "Longitude",
        }
    )

    df = df[["City", "Country", "Population", "Latitude", "Longitude"]].copy()
    df["Population"] = pd.to_numeric(df["Population"], errors="coerce").fillna(0).astype("int64")
    df["Latitude"] = pd.to_numeric(df["Latitude"], errors="coerce")
    df["Longitude"] = pd.to_numeric(df["Longitude"], errors="coerce")

    df = df.sort_values("Population", ascending=False).head(top_n)
    df["Source"] = "GeoNames"
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
    Auto-updated population estimates • Source shown in table
    </p>
    """,
    unsafe_allow_html=True,
)

# ---------- METRICS ----------
c1, c2, c3 = st.columns(3)
c1.metric("Cities Tracked", f"{len(df):,}")
c2.metric("Largest City", str(df.iloc[0]["City"]))
c3.metric("Last Update", datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))

st.divider()

# ---------- SEARCH ----------
search = st.text_input("Search city or country", "")

if search:
    filtered = df[
        df["City"].str.contains(search, case=False, na=False)
        | df["Country"].str.contains(search, case=False, na=False)
    ].copy()
else:
    filtered = df.copy()

# ---------- MAP ----------
map_df = filtered.dropna(subset=["Latitude", "Longitude"]).copy()
if not map_df.empty:
    st.subheader("City Map")
    fig_map = px.scatter_geo(
        map_df,
        lat="Latitude",
        lon="Longitude",
        size="Population",
        hover_name="City",
        hover_data={"Country": True, "Population": ":,", "Latitude": False, "Longitude": False, "Source": True},
        projection="natural earth",
        title="Top Cities (bubble size = population)",
    )
    fig_map.update_layout(height=650)
    st.plotly_chart(fig_map, use_container_width=True)
else:
    st.info("No coordinates available to plot a map for the current filter.")

# ---------- TABLE ----------
st.dataframe(
    filtered[["City", "Country", "Population", "Source"]].style.format({"Population": "{:,}"}),
    use_container_width=True,
    height=600,
)

# ---------- BAR CHART ----------
fig = px.bar(
    filtered.head(20),
    x="Population",
    y="City",
    orientation="h",
    title="Top 20 Cities by Population",
)
fig.update_layout(height=700, yaxis=dict(autorange="reversed"))
st.plotly_chart(fig, use_container_width=True)

# ---------- FOOTER ----------
st.caption(
    "Population figures are estimates, auto-refreshed hourly. "
    "True real-time city population tracking does not exist."
)
