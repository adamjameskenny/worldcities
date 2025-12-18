import math
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
import urllib.parse

import requests
import pandas as pd
import streamlit as st
import plotly.express as px

# ================== PAGE ==================
st.set_page_config(
    page_title="World City Populations",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ================== STYLE ==================
st.markdown(
    """
    <style>
      .block-container { padding-top: 1.2rem; padding-bottom: 1.2rem; }
      .title-wrap { display:flex; align-items:center; gap:12px; }
      .badge { width:44px; height:44px; border-radius:14px;
               display:flex; align-items:center; justify-content:center;
               background: rgba(96,165,250,0.14);
               border: 1px solid rgba(96,165,250,0.28); font-size:22px; }
      .subtitle { color:#94a3b8; }
      .card { background: rgba(2,6,23,0.60);
              border: 1px solid rgba(148,163,184,0.16);
              border-radius: 18px; padding: 14px; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ================== HELPERS ==================
def fmt_int(n):
    try:
        return f"{int(n):,}"
    except Exception:
        return "—"


def parse_pop(v) -> int:
    s = str(v or "")
    s = re.sub(r"[^0-9eE\+\-\.]", "", s)
    if not s:
        return 0
    try:
        return int(Decimal(s))
    except (InvalidOperation, ValueError):
        return 0


# ================== WIKIDATA ==================
WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"

@st.cache_data(ttl=24 * 3600, show_spinner="Loading cities from Wikidata…")
def load_wikidata_cities(top_n: int = 500) -> pd.DataFrame:
    query = """
    PREFIX wd: <http://www.wikidata.org/entity/>
    PREFIX wdt: <http://www.wikidata.org/prop/direct/>
    PREFIX p: <http://www.wikidata.org/prop/>
    PREFIX ps: <http://www.wikidata.org/prop/statement/>
    PREFIX pq: <http://www.wikidata.org/prop/qualifier/>
    PREFIX wikibase: <http://wikiba.se/ontology#>
    PREFIX bd: <http://www.bigdata.com/rdf#>
    PREFIX geof: <http://www.opengis.net/def/function/geosparql/>

    SELECT ?city ?cityLabel ?countryLabel ?pop ?popTime ?lat ?lon WHERE {
      ?city wdt:P31/wdt:P279* wd:Q515 ;
            wdt:P17 ?country ;
            wdt:P625 ?coord ;
            p:P1082 ?st .
      ?st ps:P1082 ?pop .
      OPTIONAL { ?st pq:P585 ?popTime . }

      BIND(geof:latitude(?coord) AS ?lat)
      BIND(geof:longitude(?coord) AS ?lon)

      SERVICE wikibase:label {
        bd:serviceParam wikibase:language "en".
      }
    }
    LIMIT 20000
    """

    headers = {
        "User-Agent": "WorldCitiesApp/1.0 (https://streamlit.io)",
        "Accept": "application/sparql-results+json",
    }

    r = requests.get(
        WIKIDATA_SPARQL_URL,
        params={"query": query, "format": "json"},
        headers=headers,
        timeout=90,
    )
    r.raise_for_status()

    data = r.json()["results"]["bindings"]

    rows = []
    for b in data:
        city_uri = b["city"]["value"]
        qid = city_uri.rsplit("/", 1)[-1]
        pop_time = b.get("popTime", {}).get("value")

        rows.append({
            "QID": qid,
            "City": b.get("cityLabel", {}).get("value", ""),
            "Country": b.get("countryLabel", {}).get("value", ""),
            "Population": parse_pop(b.get("pop", {}).get("value")),
            "Latitude": float(b.get("lat", {}).get("value")),
            "Longitude": float(b.get("lon", {}).get("value")),
            "PopTime": pop_time or "",
            "Source": "Wikidata (P1082)",
        })

    df = pd.DataFrame(rows)

    # ---- Clean + dedupe ----
    df = df.dropna(subset=["QID", "City", "Country"]).copy()
    df["Population"] = pd.to_numeric(df["Population"], errors="coerce").fillna(0).astype("int64")

    df["_t"] = pd.to_datetime(df["PopTime"], errors="coerce", utc=True)
    df["_t"] = df["_t"].dt.tz_convert(None).fillna(pd.Timestamp("1900-01-01"))

    df = df[df["Population"] > 0]

    # latest population per city entity
    df = df.sort_values(["QID", "_t", "Population"], ascending=[True, False, False])
    df = df.drop_duplicates(subset=["QID"], keep="first")

    # safety: collapse same label duplicates
    df = df.sort_values("Population", ascending=False)
    df = df.drop_duplicates(subset=["City", "Country"], keep="first")

    df = (
        df.sort_values("Population", ascending=False)
          .head(top_n)
          .reset_index(drop=True)
    )
    return df.drop(columns=["_t"])


# ================== SIDEBAR ==================
with st.sidebar:
    st.markdown("## Filters")

    if st.button("Refresh data"):
        st.cache_data.clear()
        st.rerun()

    top_n = st.select_slider("Top N cities", [100, 250, 500], value=500)
    map_n = st.select_slider("Cities on map", [50, 100, 250, 500], value=150)

    query = st.text_input("Search")

# ================== LOAD DATA ==================
df_all = load_wikidata_cities(top_n=top_n)

df = df_all.copy()
if query:
    df = df[
        df["City"].str.contains(query, case=False, na=False)
        | df["Country"].str.contains(query, case=False, na=False)
    ]

df.insert(0, "Rank", range(1, len(df) + 1))
df["PopScale"] = df["Population"].apply(lambda x: math.sqrt(x))

# ================== HEADER ==================
st.markdown(
    f"""
    <div class="title-wrap">
      <div class="badge">🌍</div>
      <div>
        <div style="font-size:38px;font-weight:800;">World City Populations</div>
        <div class="subtitle">Top {len(df)} cities • Wikidata</div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ================== MAP ==================
st.subheader("Map")

map_df = df.head(map_n)

fig = px.scatter_mapbox(
    map_df,
    lat="Latitude",
    lon="Longitude",
    size="PopScale",
    hover_name="City",
    hover_data={"Country": True, "Population": ":,", "Rank": True},
    zoom=1,
    height=650,
)
fig.update_layout(mapbox_style="carto-darkmatter", margin=dict(l=0, r=0, t=0, b=0))
st.plotly_chart(fig, use_container_width=True)

# ================== TABLE ==================
st.subheader("Cities")

st.dataframe(
    df[["Rank", "City", "Country", "Population", "Source"]],
    use_container_width=True,
    height=520,
)

# ================== FOOTER ==================
st.caption(
    "Population source: Wikidata (P1082). Coordinates: Wikidata (P625). "
    "Definitions vary by city."
)

