import math
import re
import io
import zipfile
from datetime import datetime
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

st.markdown(
    """
    <style>
      .block-container { padding-top: 1.2rem; padding-bottom: 1.2rem; }
      .title-wrap { display:flex; align-items:center; gap:12px; margin-bottom: 6px; }
      .badge { width:44px; height:44px; border-radius:14px; display:flex; align-items:center; justify-content:center;
               background: rgba(96,165,250,0.14); border: 1px solid rgba(96,165,250,0.28); font-size:22px; }
      .subtitle { color:#94a3b8; margin-top:-6px; }
      .chip { display:inline-block; padding:4px 10px; border-radius:999px;
              background: rgba(148,163,184,0.12); border: 1px solid rgba(148,163,184,0.18);
              color:#cbd5e1; font-size:12px; margin-right: 6px; }
      .card { background: rgba(2,6,23,0.60); border: 1px solid rgba(148,163,184,0.16);
              border-radius: 18px; padding: 14px; }
      .muted { color:#94a3b8; }
      .big { color:#e5e7eb; font-size:22px; font-weight:780; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
      .kpi-label { color:#94a3b8; font-size:12px; letter-spacing:0.02em; }
      .kpi-sub { color:#94a3b8; font-size:12px; margin-top:6px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ================== HELPERS ==================
def fmt_int(n) -> str:
    try:
        return f"{int(n):,}"
    except Exception:
        return "—"


def kpi_card(label: str, value: str, sub: str = ""):
    st.markdown(
        f"""
        <div class="card" style="min-height: 92px;">
          <div class="kpi-label">{label}</div>
          <div class="big" style="margin-top:6px;">{value}</div>
          <div class="kpi-sub">{sub}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ================== WIKIPEDIA POPULATION (TOP CITIES) ==================
WIKI_LARGEST_CITIES_URL = "https://en.wikipedia.org/wiki/List_of_largest_cities"

@st.cache_data(ttl=7 * 24 * 3600, show_spinner="Loading Wikipedia city populations…")
def load_wikipedia_populations() -> pd.DataFrame:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; CityPopApp/1.0; +https://streamlit.io)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    r = requests.get(WIKI_LARGEST_CITIES_URL, headers=headers, timeout=30)
    r.raise_for_status()

    # IMPORTANT: pass HTML content, not the URL (avoids urllib blocks)
    tables = pd.read_html(r.text)

    df = tables[0].copy()
    df.columns = [str(c).strip().lower() for c in df.columns]

    def find_col(patterns):
        for p in patterns:
            rx = re.compile(p)
            for c in df.columns:
                if rx.search(c):
                    return c
        return None

    city_c = find_col([r"^city", r"urban", r"agglomeration", r"name"])
    country_c = find_col([r"^country", r"state"])
    pop_c = find_col([r"pop", r"population"])

    if not all([city_c, country_c, pop_c]):
        raise RuntimeError(f"Could not parse Wikipedia table columns: {df.columns.tolist()}")

    out = pd.DataFrame({
        "City": df[city_c].astype(str),
        "Country": df[country_c].astype(str),
        "Population": (
            df[pop_c].astype(str)
            .str.replace(r"\[.*?\]", "", regex=True)   # strip citations
            .str.replace(r"[^\d]", "", regex=True)     # digits only
        ),
    })

    out["City"] = out["City"].str.replace(r"\[.*?\]", "", regex=True).str.strip()
    out["Country"] = out["Country"].str.replace(r"\[.*?\]", "", regex=True).str.strip()
    out["Population"] = pd.to_numeric(out["Population"], errors="coerce").fillna(0).astype("int64")

    out["Source"] = "Wikipedia (List of largest cities)"
    out = out.dropna(subset=["City", "Country"])
    out = out[out["Population"] > 0].sort_values("Population", ascending=False).reset_index(drop=True)
    return out



# ================== GEO COORDINATES (GEONAMES) ==================
GEONAMES_URL = "https://download.geonames.org/export/dump/cities15000.zip"
HEADERS = {"User-Agent": "CityPopApp/1.0 (+https://streamlit.io)"}

@st.cache_data(ttl=30 * 24 * 3600, show_spinner="Loading coordinates (GeoNames)…")
def load_geonames_coords() -> pd.DataFrame:
    r = requests.get(GEONAMES_URL, headers=HEADERS, timeout=60)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    with z.open("cities15000.txt") as f:
        cols = [
            "geonameid","name","asciiname","alternatenames","latitude","longitude","feature_class",
            "feature_code","country_code","cc2","admin1_code","admin2_code","admin3_code","admin4_code",
            "population","elevation","dem","timezone","modification_date"
        ]
        gdf = pd.read_csv(f, sep="\t", header=None, names=cols, low_memory=False)

    coords = gdf.rename(columns={"name": "City", "country_code": "CountryCode", "latitude": "Latitude", "longitude": "Longitude"})
    coords["City"] = coords["City"].astype(str).str.strip()
    coords["Latitude"] = pd.to_numeric(coords["Latitude"], errors="coerce")
    coords["Longitude"] = pd.to_numeric(coords["Longitude"], errors="coerce")

    # Keep only best candidate per (City, CountryCode): prefer larger local geonames population
    coords["GN_Pop"] = pd.to_numeric(coords["population"], errors="coerce").fillna(0).astype("int64")
    coords = coords.sort_values("GN_Pop", ascending=False).drop_duplicates(subset=["City", "CountryCode"], keep="first")
    return coords[["City", "CountryCode", "Latitude", "Longitude", "GN_Pop"]].reset_index(drop=True)


# ================== WIKIPEDIA CITY PROFILE (HISTORY/CULTURE) ==================
@st.cache_data(ttl=7 * 24 * 3600)
def wiki_summary(city: str, country: str) -> dict:
    def fetch(title: str):
        t = urllib.parse.quote(title.replace(" ", "_"))
        api = f"https://en.wikipedia.org/api/rest_v1/page/summary/{t}"
        r = requests.get(api, headers={"User-Agent": "CityPopApp/1.0"}, timeout=10)
        if r.status_code != 200:
            return None
        j = r.json()
        if j.get("type") == "disambiguation":
            return None
        extract = (j.get("extract") or "").strip()
        url = (j.get("content_urls", {}) or {}).get("desktop", {}).get("page", "")
        if not extract:
            return None
        first_para = extract.split("\n\n")[0].strip()
        return {"title": j.get("title", title), "extract": first_para, "url": url}

    for title in (f"{city}, {country}", city):
        out = fetch(title)
        if out:
            return out
    return {"title": city, "extract": "No Wikipedia summary found.", "url": ""}


# ================== SIDEBAR ==================
with st.sidebar:
    st.markdown("## Filters")
    st.caption("Wikipedia for populations • GeoNames for coordinates • Wikipedia for city profiles")

    if st.button("Refresh (clear cache)"):
        st.cache_data.clear()
        st.rerun()

    top_n = st.select_slider("Top N cities", options=[100, 250, 500], value=500)
    map_n = st.select_slider("Cities shown on map", options=[50, 100, 150, 250, 500], value=min(150, top_n))

    query = st.text_input("Search", placeholder="City or country…")
    only_mapped = st.toggle("Only cities with coordinates", value=False)
    log_bubbles = st.toggle("Log bubble sizing", value=False)

    st.markdown("<hr style='border:0;height:1px;background:rgba(148,163,184,0.15);'/>", unsafe_allow_html=True)
    st.caption("Populations are not real-time counts; they reflect source methodology.")


# ================== LOAD + MERGE DATA ==================
pop_df = load_wikipedia_populations()

# Country names from Wikipedia won't match GeoNames country codes. We only use GeoNames by city name.
coords_df = load_geonames_coords()

# Merge on City only (best-effort). For top cities this works reasonably well.
df_all = pop_df.merge(coords_df[["City", "Latitude", "Longitude"]], on="City", how="left")

# Filter/search
df = df_all.copy()
if query:
    df = df[
        df["City"].str.contains(query, case=False, na=False) |
        df["Country"].str.contains(query, case=False, na=False)
    ]

df = df.sort_values("Population", ascending=False).head(top_n).reset_index(drop=True)
df.insert(0, "Rank", df.index + 1)

if only_mapped:
    df = df.dropna(subset=["Latitude", "Longitude"]).reset_index(drop=True)
    df["Rank"] = range(1, len(df) + 1)

# Bubble scaling
if log_bubbles:
    df["PopScale"] = df["Population"].apply(lambda x: math.log10(max(int(x), 1)))
else:
    df["PopScale"] = df["Population"].apply(lambda x: math.sqrt(max(int(x), 0)))


# ================== HEADER ==================
st.markdown(
    f"""
    <div class="title-wrap">
      <div class="badge">🌍</div>
      <div>
        <div style="font-size: 40px; font-weight: 780; line-height: 1.05;">World City Populations</div>
        <div class="subtitle">Top {top_n} • Click a city in Table to view profile</div>
      </div>
    </div>
    <span class="chip">Population source: Wikipedia</span>
    <span class="chip">Coords source: GeoNames</span>
    <span class="chip">Updated: {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}</span>
    """,
    unsafe_allow_html=True,
)

st.write("")

# ================== KPI ROW ==================
if "selected_rank" not in st.session_state:
    st.session_state.selected_rank = None

total_pop = int(df["Population"].sum()) if not df.empty else 0
median_pop = int(df["Population"].median()) if not df.empty else 0
over_10m = int((df["Population"] >= 10_000_000).sum()) if not df.empty else 0

largest_city = str(df.iloc[0]["City"]) if not df.empty else "—"
largest_country = str(df.iloc[0]["Country"]) if not df.empty else "—"
largest_pop = int(df.iloc[0]["Population"]) if not df.empty else 0

c1, c2, c3, c4, c5 = st.columns(5)
with c1: kpi_card("Cities shown", fmt_int(len(df)), f"Top {top_n}")
with c2: kpi_card("Largest city", largest_city, largest_country)
with c3: kpi_card("Largest population", fmt_int(largest_pop), "Population")
with c4: kpi_card("Median population", fmt_int(median_pop), "Across selection")
with c5: kpi_card("Cities ≥ 10M", fmt_int(over_10m), f"Total pop shown: {fmt_int(total_pop)}")


# ================== TABS ==================
tab_dash, tab_table, tab_map, tab_charts, tab_about = st.tabs(["Dashboard", "Table", "Map", "Charts", "About"])

with tab_dash:
    left, right = st.columns([1.6, 1], gap="large")

    with left:
        st.subheader("Map")
        map_df = df.head(map_n).dropna(subset=["Latitude", "Longitude"]).copy()
        if map_df.empty:
            st.info("No coordinates available in the current view.")
        else:
            fig = px.scatter_mapbox(
                map_df,
                lat="Latitude",
                lon="Longitude",
                size="PopScale",
                hover_name="City",
                hover_data={"Country": True, "Population": ":,", "Rank": True, "PopScale": False},
                zoom=1,
                height=640,
            )
            fig.update_layout(mapbox_style="carto-darkmatter", margin=dict(l=0, r=0, t=0, b=0))

            # highlight selected
            selected = None
            if st.session_state.selected_rank is not None:
                hit = df[df["Rank"] == st.session_state.selected_rank]
                if not hit.empty:
                    selected = hit.iloc[0]

            if selected is not None and pd.notna(selected["Latitude"]) and pd.notna(selected["Longitude"]):
                hi = pd.DataFrame([selected])
                fig_hi = px.scatter_mapbox(hi, lat="Latitude", lon="Longitude", hover_name="City", zoom=2, height=640)
                fig_hi.update_traces(marker={"size": 22, "opacity": 0.95})
                for tr in fig_hi.data:
                    fig.add_trace(tr)

            st.plotly_chart(fig, use_container_width=True)

    with right:
        st.subheader("City panel")

        sel_rank = st.session_state.selected_rank
        if sel_rank is None:
            st.info("Select a city in the Table tab.")
        else:
            hit = df[df["Rank"] == sel_rank]
            if hit.empty:
                st.info("Selected city not in current filter/search.")
            else:
                row = hit.iloc[0]
                st.markdown(
                    f"""
                    <div class="card">
                      <div style="font-size:18px; font-weight:850; color:#e5e7eb;">{row['City']}</div>
                      <div class="muted" style="margin-top:4px;">{row['Country']} • Rank {int(row['Rank'])}</div>
                      <div style="margin-top:10px; color:#e5e7eb;">Population: <b>{fmt_int(row['Population'])}</b></div>
                      <div class="muted" style="margin-top:6px;">Source: {row['Source']}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                st.write("")
                st.subheader("History & culture (Wikipedia)")
                info = wiki_summary(str(row["City"]), str(row["Country"]))
                st.markdown(
                    f"""
                    <div class="card">
                      <div style="font-size:15px; font-weight:800; color:#e5e7eb;">{info['title']}</div>
                      <div class="muted" style="margin-top:8px; line-height:1.55;">{info['extract']}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if info["url"]:
                    st.link_button("Open Wikipedia", info["url"])

        st.write("")
        st.subheader("Top 10")
        top10 = df.head(10)[["Rank", "City", "Country", "Population"]].copy()
        top10["Population"] = top10["Population"].map(fmt_int)
        st.dataframe(top10, use_container_width=True, height=320, hide_index=True)

with tab_table:
    st.subheader("Cities")

    table_cols = ["Rank", "City", "Country", "Population", "Latitude", "Longitude", "Source"]
    table_df = df[table_cols].copy()

    event = st.dataframe(
        table_df,
        use_container_width=True,
        height=620,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="city_table",
    )

    sel_rows = []
    try:
        sel_rows = event.selection.rows
    except Exception:
        sel_rows = []

    if sel_rows:
        st.session_state.selected_rank = int(table_df.iloc[sel_rows[0]]["Rank"])

    csv = df[["Rank", "City", "Country", "Population", "Source"]].to_csv(index=False).encode("utf-8")
    st.download_button("Download CSV", data=csv, file_name=f"top_{top_n}_cities.csv", mime="text/csv")

with tab_map:
    st.subheader("Map")

    map_df = df.head(map_n).dropna(subset=["Latitude", "Longitude"]).copy()
    if map_df.empty:
        st.info("No coordinates available in the current view.")
    else:
        fig = px.scatter_mapbox(
            map_df,
            lat="Latitude",
            lon="Longitude",
            size="PopScale",
            hover_name="City",
            hover_data={"Country": True, "Population": ":,", "Rank": True, "PopScale": False},
            zoom=1,
            height=720,
        )
        fig.update_layout(mapbox_style="carto-darkmatter", margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig, use_container_width=True)

with tab_charts:
    left, right = st.columns([1, 1], gap="large")

    with left:
        st.subheader("Top cities (bar)")
        k = st.select_slider("Top K", options=[10, 20, 50, 100], value=min(20, len(df)))
        log_x = st.toggle("Log scale (Population)", value=False)
        fig_bar = px.bar(df.head(k), x="Population", y="City", orientation="h", height=620)
        fig_bar.update_layout(yaxis=dict(autorange="reversed"), margin=dict(l=0, r=0, t=40, b=0))
        if log_x:
            fig_bar.update_xaxes(type="log")
        st.plotly_chart(fig_bar, use_container_width=True)

    with right:
        st.subheader("Population distribution")
        fig_hist = px.histogram(df, x="Population", nbins=30, height=300)
        fig_hist.update_layout(margin=dict(l=0, r=0, t=40, b=0))
        st.plotly_chart(fig_hist, use_container_width=True)

        st.subheader("Treemap")
        fig_tree = px.treemap(df, path=["Country", "City"], values="Population", height=360)
        fig_tree.update_layout(margin=dict(l=0, r=0, t=40, b=0))
        st.plotly_chart(fig_tree, use_container_width=True)

with tab_about:
    st.markdown(
        """
**Sources**
- Populations: Wikipedia table (“List of largest cities”)
- Coordinates: GeoNames cities15000
- City profile text: Wikipedia REST summary API

**Notes**
- Population definitions differ across cities (city proper vs metro/urban area) depending on source conventions.
- This app caches data to be fast and avoid rate limits.
        """
    )

