import io
import zipfile
from datetime import datetime
import math

import requests
import pandas as pd
import streamlit as st
import plotly.express as px

# ------------------ PAGE ------------------
st.set_page_config(page_title="World City Populations", layout="wide", initial_sidebar_state="expanded")

st.markdown(
    """
    <style>
      .block-container { padding-top: 1.2rem; padding-bottom: 1.2rem; }
      .title-wrap { display:flex; align-items:center; gap:12px; margin-bottom: 6px; }
      .badge { width:44px; height:44px; border-radius:14px; display:flex; align-items:center; justify-content:center;
               background: rgba(74,222,128,0.12); border: 1px solid rgba(74,222,128,0.25); font-size:22px; }
      .subtitle { color:#94a3b8; margin-top:-6px; }
      .chip { display:inline-block; padding:4px 10px; border-radius:999px;
              background: rgba(148,163,184,0.12); border: 1px solid rgba(148,163,184,0.18);
              color:#cbd5e1; font-size:12px; }
      div[data-testid="stMetric"] { background: rgba(2,6,23,0.55); border: 1px solid rgba(148,163,184,0.14);
                                   padding: 14px 14px; border-radius: 16px; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ------------------ SOURCES ------------------
WPR_URL = "https://worldpopulationreview.com/static/cities.json"
GEONAMES_URL = "https://download.geonames.org/export/dump/cities15000.zip"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CityPopApp/1.0; +https://streamlit.io)",
    "Accept": "application/json,text/plain,*/*",
}

# ------------------ DATA ------------------
@st.cache_data(ttl=3600)
def load_data() -> pd.DataFrame:
    # Primary: WorldPopulationReview
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
        df["Source"] = "WorldPopulationReview"
        return df[["City", "Country", "Population", "Latitude", "Longitude", "Source"]].dropna(subset=["City", "Country"])
    except Exception:
        pass

    # Fallback: GeoNames
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
    df["Population"] = pd.to_numeric(df["Population"], errors="coerce").fillna(0).astype("int64")
    df["Latitude"] = pd.to_numeric(df["Latitude"], errors="coerce")
    df["Longitude"] = pd.to_numeric(df["Longitude"], errors="coerce")
    df["Source"] = "GeoNames"
    return df[["City", "Country", "Population", "Latitude", "Longitude", "Source"]].dropna(subset=["City", "Country"])


# ------------------ SIDEBAR CONTROLS ------------------
with st.sidebar:
    st.markdown("### Controls")

    if st.button("Refresh data (clears cache)"):
        st.cache_data.clear()
        st.rerun()

  top_n = st.select_slider("Top N cities", options=[50, 100, 150, 200, 250], value=250)
map_n = st.select_slider("Cities shown on map", options=[25, 50, 100, 150, 250], value=min(100, top_n))


    df_all = load_data()
    max_pop = int(df_all["Population"].max()) if not df_all.empty else 0
    min_pop = st.slider(
        "Minimum population",
        min_value=0,
        max_value=max_pop if max_pop > 0 else 1,
        value=0,
        step=max(1, max_pop // 200) if max_pop > 0 else 1,
        format="%d",
    )

    countries = sorted(df_all["Country"].dropna().unique().tolist())
    selected_countries = st.multiselect("Countries", options=countries, default=[])

    query = st.text_input("Search", placeholder="City or country…")

    st.markdown("---")
    st.caption("Cache refresh: ~hourly (data source dependent).")

# ------------------ FILTER / PREP ------------------
df = df_all.copy()
df = df[df["Population"] >= min_pop]

if selected_countries:
    df = df[df["Country"].isin(selected_countries)]

if query:
    df = df[
        df["City"].str.contains(query, case=False, na=False)
        | df["Country"].str.contains(query, case=False, na=False)
    ]

df = df.sort_values("Population", ascending=False).head(top_n).reset_index(drop=True)
df.insert(0, "Rank", df.index + 1)

# bubble scale: sqrt(pop) to reduce dominance
df["PopScale"] = df["Population"].apply(lambda x: math.sqrt(max(x, 0)))

# ------------------ HEADER + METRICS ------------------
st.markdown(
    f"""
    <div class="title-wrap">
      <div class="badge">🌍</div>
      <div>
        <div style="font-size: 40px; font-weight: 750; line-height: 1.05;">World City Populations</div>
        <div class="subtitle">Top {top_n} • Filterable • Map + table + charts</div>
      </div>
    </div>
    <span class="chip">Source: {df['Source'].iloc[0] if not df.empty else "—"}</span>
    <span class="chip">Updated: {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}</span>
    """,
    unsafe_allow_html=True,
)

st.write("")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Cities shown", f"{len(df):,}")
c2.metric("Largest city", str(df.iloc[0]["City"]) if not df.empty else "—")
c3.metric("Largest population", f"{int(df.iloc[0]['Population']):,}" if not df.empty else "—")
c4.metric("Distinct countries", f"{df['Country'].nunique():,}" if not df.empty else "—")

st.write("")

# ------------------ TABS ------------------
tab_map, tab_table, tab_charts, tab_about = st.tabs(["Map", "Table", "Charts", "About"])

with tab_map:
   map_df = df.head(map_n).dropna(subset=["Latitude", "Longitude"]).copy()

    if map_df.empty:
        st.info("No coordinates available for the current selection.")
    else:
        fig_map = px.scatter_mapbox(
            map_df,
            lat="Latitude",
            lon="Longitude",
            size="PopScale",
            hover_name="City",
            hover_data={"Country": True, "Population": ":,", "Rank": True, "PopScale": False},
            zoom=1,
            height=680,
        )
        fig_map.update_layout(
            mapbox_style="carto-darkmatter",
            margin=dict(l=0, r=0, t=0, b=0),
        )
        st.plotly_chart(fig_map, use_container_width=True)

with tab_table:
    show_cols = ["Rank", "City", "Country", "Population", "Source"]
    st.dataframe(
        df[show_cols].style.format({"Population": "{:,}"}),
        use_container_width=True,
        height=680,
    )

    csv = df[show_cols].to_csv(index=False).encode("utf-8")
    st.download_button("Download CSV", data=csv, file_name=f"top_{top_n}_cities.csv", mime="text/csv")

with tab_charts:
    left, right = st.columns([1, 1])

    with left:
        k = st.select_slider("Bar chart: Top K", options=[10, 20, 50], value=min(20, len(df)))
        fig_bar = px.bar(
            df.head(k),
            x="Population",
            y="City",
            orientation="h",
            height=720,
        )
        fig_bar.update_layout(yaxis=dict(autorange="reversed"), margin=dict(l=0, r=0, t=40, b=0))
        st.plotly_chart(fig_bar, use_container_width=True)

    with right:
        fig_country = px.treemap(
            df,
            path=["Country", "City"],
            values="Population",
            height=720,
        )
        fig_country.update_layout(margin=dict(l=0, r=0, t=40, b=0))
        st.plotly_chart(fig_country, use_container_width=True)

with tab_about:
    st.markdown(
        """
**What you’re seeing**
- City populations are **estimates** (typically updated monthly/quarterly at best).
- The app refreshes its cached data about **hourly**; press **Refresh data** to force reload.

**Data source behavior**
- Primary: WorldPopulationReview (can be blocked on some hosts).
- Fallback: GeoNames (stable, broad coverage; populations are also estimates).
        """
    )

