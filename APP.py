import io
import zipfile
from datetime import datetime
import math

import requests
import pandas as pd
import streamlit as st
import plotly.express as px

# ------------------ PAGE ------------------
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
               background: rgba(74,222,128,0.12); border: 1px solid rgba(74,222,128,0.25); font-size:22px; }
      .subtitle { color:#94a3b8; margin-top:-6px; }
      .chip { display:inline-block; padding:4px 10px; border-radius:999px;
              background: rgba(148,163,184,0.12); border: 1px solid rgba(148,163,184,0.18);
              color:#cbd5e1; font-size:12px; margin-right: 6px; }
      div[data-testid="stMetric"] { background: rgba(2,6,23,0.55); border: 1px solid rgba(148,163,184,0.14);
                                   padding: 14px 14px; border-radius: 16px; }
    </style>
    """,
    unsafe_allow_html=True,
)
def fmt_int(n) -> str:
    try:
        return f"{int(n):,}"
    except Exception:
        return "—"

def kpi_card(label: str, value: str, sub: str = ""):
    st.markdown(
        f"""
        <div style="
            background: rgba(2,6,23,0.60);
            border: 1px solid rgba(148,163,184,0.16);
            border-radius: 18px;
            padding: 14px 14px;
            min-height: 92px;">
          <div style="color:#94a3b8; font-size:12px; letter-spacing:0.02em;">{label}</div>
          <div style="color:#e5e7eb; font-size:22px; font-weight:780; margin-top:6px;
                      white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
            {value}
          </div>
          <div style="color:#94a3b8; font-size:12px; margin-top:6px;
                      white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
            {sub}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
import urllib.parse

@st.cache_data(ttl=7 * 24 * 3600)  # cache for a week
def wiki_summary(city: str, country: str) -> dict:
    """
    Returns {title, extract, url} using Wikipedia REST summary.
    Tries 'City, Country' first, then 'City'.
    """
    def fetch(title: str):
        t = urllib.parse.quote(title.replace(" ", "_"))
        api = f"https://en.wikipedia.org/api/rest_v1/page/summary/{t}"
        r = requests.get(api, headers={"User-Agent": "CityPopApp/1.0"}, timeout=10)
        if r.status_code != 200:
            return None
        j = r.json()
        # Skip disambiguation pages
        if j.get("type") == "disambiguation":
            return None
        extract = j.get("extract") or ""
        url = (j.get("content_urls", {}) or {}).get("desktop", {}).get("page", "")
        return {"title": j.get("title", title), "extract": extract, "url": url}

    # Common patterns
    for title in (f"{city}, {country}", city):
        out = fetch(title)
        if out and out["extract"]:
            # “short paragraph”: first paragraph only
            first_para = out["extract"].split("\n\n")[0].strip()
            out["extract"] = first_para
            return out

    return {"title": city, "extract": "No summary found.", "url": ""}

# ------------------ SOURCES ------------------
WPR_URL = "https://worldpopulationreview.com/static/cities.json"
GEONAMES_URL = "https://download.geonames.org/export/dump/cities15000.zip"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CityPopApp/1.0; +https://streamlit.io)",
    "Accept": "application/json,text/plain,*/*",
}

# ------------------ DATA ------------------
@st.cache_data(ttl=7 * 24 * 3600, show_spinner="Loading Wikipedia city data…")
def load_data(top_n: int = 500) -> pd.DataFrame:
    url = "https://en.wikipedia.org/wiki/List_of_largest_cities"
    tables = pd.read_html(url)

    # The first table is the ranked city population table
    df = tables[0]

    # Normalize column names (Wikipedia can change labels slightly)
    df.columns = [c.lower() for c in df.columns]

    df = df.rename(columns={
        "city": "City",
        "country": "Country",
        "population": "Population",
    })

    # Clean population
    df["Population"] = (
        df["Population"]
        .astype(str)
        .str.replace(r"[^\d]", "", regex=True)
        .astype("int64")
    )

    df = df[["City", "Country", "Population"]]
    df["Source"] = "Wikipedia (List of largest cities)"

    df = df.sort_values("Population", ascending=False).head(top_n).reset_index(drop=True)
    return df




# ------------------ SIDEBAR ------------------
with st.sidebar:
    st.markdown("## Filters")
    st.caption("Refine the view. The dashboard updates instantly.")


    if st.button("Refresh data (clear cache)"):
        st.cache_data.clear()
        st.rerun()

    top_n = st.select_slider(
    "Top N cities",
    options=[100, 250, 500],
    value=500,
)

    map_n = st.select_slider(
        "Cities shown on map",
        options=[50, 100, 150, 250, 500],
        value=min(150, top_n),

    )

    df_all = load_data()
    max_pop = int(df_all["Population"].max()) if not df_all.empty else 0

    min_pop = st.slider(
        "Minimum population",
        min_value=0,
        max_value=max_pop if max_pop > 0 else 1,
        value=0,
        step=max(1, max_pop // 250) if max_pop > 0 else 1,
    )

    countries = sorted(df_all["Country"].dropna().unique().tolist())
    selected_countries = st.multiselect("Countries", options=countries, default=[])

    query = st.text_input("Search", placeholder="City or country…")
    only_mapped = st.toggle("Only cities with coordinates", value=False)
    log_bubbles = st.toggle("Log bubble sizing", value=False)


    st.markdown("<hr style='border:0;height:1px;background:rgba(148,163,184,0.15);'/>", unsafe_allow_html=True)
    st.caption("Cache refresh: ~hourly (source dependent).")

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

# bubble scaling
df["PopScale"] = df["Population"].apply(lambda x: math.sqrt(max(int(x), 0)))
if only_mapped:
    df = df.dropna(subset=["Latitude", "Longitude"])
if log_bubbles:
    df["PopScale"] = df["Population"].apply(lambda x: math.log10(max(int(x), 1)))
else:
    df["PopScale"] = df["Population"].apply(lambda x: math.sqrt(max(int(x), 0)))


# ------------------ HEADER ------------------
source_chip = df["Source"].iloc[0] if not df.empty else "—"
st.markdown(
    f"""
    <div class="title-wrap">
      <div class="badge">🌍</div>
      <div>
        <div style="font-size: 40px; font-weight: 750; line-height: 1.05;">World City Populations</div>
        <div class="subtitle">Top {top_n} • Map + table + charts</div>
      </div>
    </div>
    <span class="chip">Source: {source_chip}</span>
    <span class="chip">Updated: {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}</span>
    """,
    unsafe_allow_html=True,
)

st.write("")

# ------------------ METRICS ------------------
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
with c5: kpi_card("Cities ≥ 10M", fmt_int(over_10m), f"Total shown: {fmt_int(total_pop)}")


# ------------------ TABS ------------------
tab_dash, tab_map, tab_table, tab_charts, tab_about = st.tabs(["Dashboard", "Map", "Table", "Charts", "About"])
with tab_dash:
    left, right = st.columns([1.6, 1], gap="large")

    with left:
        st.subheader("Map")
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
                height=640,
            )
            fig_map.update_layout(mapbox_style="carto-darkmatter", margin=dict(l=0, r=0, t=0, b=0))

            # highlight selected
            selected = None
            if st.session_state.get("selected_rank") is not None:
                hit = df[df["Rank"] == st.session_state.selected_rank]
                if not hit.empty:
                    selected = hit.iloc[0]

            if selected is not None and pd.notna(selected["Latitude"]) and pd.notna(selected["Longitude"]):
                hi = pd.DataFrame([selected])
                fig_hi = px.scatter_mapbox(hi, lat="Latitude", lon="Longitude", hover_name="City", zoom=2, height=640)
                fig_hi.update_traces(marker={"size": 22, "opacity": 0.95})
                for tr in fig_hi.data:
                    fig_map.add_trace(tr)

            st.plotly_chart(fig_map, use_container_width=True)

    with right:
        st.subheader("Selected city")
        sel_rank = st.session_state.get("selected_rank")
        if sel_rank is None:
            st.info("Select a city in the Table tab to see details here.")
        else:
            hit = df[df["Rank"] == sel_rank]
            if hit.empty:
                st.info("Selected city not in current filter.")
            else:
                row = hit.iloc[0]
                st.markdown(
                    f"""
                    <div style="background: rgba(2,6,23,0.55);
                                border: 1px solid rgba(148,163,184,0.16);
                                border-radius: 18px; padding: 14px;">
                      <div style="font-size:18px; font-weight:850; color:#e5e7eb;">
                        {row['City']}
                      </div>
                      <div style="color:#94a3b8; margin-top:4px;">
                        {row['Country']} • Rank {int(row['Rank'])}
                      </div>
                      <div style="margin-top:10px; color:#e5e7eb;">
                        Population: <b>{fmt_int(row['Population'])}</b>
                      </div>
                      <div style="color:#94a3b8; margin-top:6px;">
                        Source: {row['Source']}
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        st.write("")
        st.subheader("Top 10")
        top10 = df.head(10)[["Rank", "City", "Country", "Population"]].copy()
        top10["Population"] = top10["Population"].map(fmt_int)
        st.dataframe(top10, use_container_width=True, height=360, hide_index=True)


# We'll store the selected city rank in session_state so Map + Table stay in sync
if "selected_rank" not in st.session_state:
    st.session_state.selected_rank = None
    st.subheader("City profile")
sel_rank = st.session_state.get("selected_rank")
if sel_rank is None:
    st.info("Select a city in the Table tab.")
else:
    hit = df[df["Rank"] == sel_rank]
    if hit.empty:
        st.info("Selected city not in current filter.")
    else:
        row = hit.iloc[0]
        info = wiki_summary(str(row["City"]), str(row["Country"]))

        st.markdown(
            f"""
            <div style="background: rgba(2,6,23,0.55);
                        border: 1px solid rgba(148,163,184,0.16);
                        border-radius: 18px; padding: 14px;">
              <div style="font-size:16px; font-weight:850; color:#e5e7eb;">
                {info['title']}
              </div>
              <div style="color:#94a3b8; margin-top:6px; line-height:1.55;">
                {info['extract']}
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if info["url"]:
            st.link_button("Open Wikipedia", info["url"])


with tab_table:
    st.markdown("### Cities")

    table_cols = ["Rank", "City", "Country", "Population", "Source", "Latitude", "Longitude"]
    table_df = df[table_cols].copy()

    event = st.dataframe(
        table_df,
        use_container_width=True,
        height=520,
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

    selected_row = table_df.iloc[sel_rows[0]] if sel_rows else None
    if selected_row is not None:
        st.session_state.selected_rank = int(selected_row["Rank"])

    colA, colB = st.columns([2, 1])
    with colA:
        csv = df[["Rank", "City", "Country", "Population", "Source"]].to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download CSV",
            data=csv,
            file_name=f"top_{top_n}_cities.csv",
            mime="text/csv",
        )
    with colB:
        st.caption("Select a row to see details and highlight it on the map.")

    if selected_row is not None:
        st.markdown("### Selected city")
        st.markdown(
            f"""
            <div style="background: rgba(2,6,23,0.55);
                        border: 1px solid rgba(148,163,184,0.16);
                        border-radius: 18px; padding: 14px;">
              <div style="font-size:18px; font-weight:850; color:#e5e7eb;">
                {selected_row['City']}
              </div>
              <div style="color:#94a3b8; margin-top:4px;">
                {selected_row['Country']} • Rank {int(selected_row['Rank'])}
              </div>
              <div style="margin-top:10px; color:#e5e7eb;">
                Population: <b>{fmt_int(selected_row['Population'])}</b>
              </div>
              <div style="color:#94a3b8; margin-top:6px;">
                Source: {selected_row['Source']}
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

with tab_map:
    map_df = df.head(map_n).dropna(subset=["Latitude", "Longitude"]).copy()

    selected = None
    if st.session_state.selected_rank is not None:
        hit = df[df["Rank"] == st.session_state.selected_rank]
        if not hit.empty:
            selected = hit.iloc[0]

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

        # highlight selected city (if it has coords)
        if selected is not None and pd.notna(selected["Latitude"]) and pd.notna(selected["Longitude"]):
            hi = pd.DataFrame([selected])
            fig_hi = px.scatter_mapbox(
                hi,
                lat="Latitude",
                lon="Longitude",
                hover_name="City",
                zoom=2,
                height=680,
            )
            fig_hi.update_traces(marker={"size": 22, "opacity": 0.95})
            for tr in fig_hi.data:
                fig_map.add_trace(tr)

        st.plotly_chart(fig_map, use_container_width=True)

with tab_charts:
    left, right = st.columns([1, 1])

    with left:
        k = st.select_slider("Bar chart: Top K", options=[10, 20, 50, 100], value=min(20, len(df)))
        log_x = st.toggle("Log scale (Population)", value=False)
        fig_bar = px.bar(df.head(k), x="Population", y="City", orientation="h", height=720)
        fig_bar.update_layout(yaxis=dict(autorange="reversed"), margin=dict(l=0, r=0, t=40, b=0))
        if log_x:
            fig_bar.update_xaxes(type="log")
        st.plotly_chart(fig_bar, use_container_width=True)

    with right:
        fig_tree = px.treemap(df, path=["Country", "City"], values="Population", height=720)
        fig_tree.update_layout(margin=dict(l=0, r=0, t=40, b=0))
        st.plotly_chart(fig_tree, use_container_width=True)
        st.subheader("Population distribution")
fig_hist = px.histogram(df, x="Population", nbins=30, height=320)
fig_hist.update_layout(margin=dict(l=0, r=0, t=40, b=0))
st.plotly_chart(fig_hist, use_container_width=True)


with tab_about:
    st.markdown(
        """
**Notes**
- City populations are estimates (not live counts).
- This app caches results about hourly (source dependent).
- Primary source may occasionally block hosts; app falls back to GeoNames.
        """
    )









