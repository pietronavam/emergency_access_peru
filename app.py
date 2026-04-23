"""
app.py — Streamlit application: Emergency Healthcare Access Inequality in Peru.

Structure
---------
Tab 1 — Data & Methodology
Tab 2 — Static Analysis
Tab 3 — GeoSpatial Results
Tab 4 — Interactive Exploration
"""

from pathlib import Path

import geopandas as gpd
import pandas as pd
import streamlit as st

from src.utils import DATA_PROC, OUTPUT_FIGS, OUTPUT_TABS

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Emergency Access Peru",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Data loaders (cached) ─────────────────────────────────────────────────────

@st.cache_data
def load_metrics() -> gpd.GeoDataFrame | None:
    p = DATA_PROC / "district_metrics.geojson"
    if not p.exists():
        return None
    return gpd.read_file(p)


@st.cache_data
def load_comparison() -> pd.DataFrame | None:
    p = OUTPUT_TABS / "specification_comparison.csv"
    if not p.exists():
        return None
    return pd.read_csv(p)


@st.cache_data
def load_ipress() -> gpd.GeoDataFrame | None:
    p = DATA_PROC / "ipress_clean.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    from src.geospatial import build_gdf_ipress
    try:
        return build_gdf_ipress(df)
    except Exception:
        return None


def fig_path(name: str) -> Path:
    return OUTPUT_FIGS / name


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pipeline_warning():
    st.warning(
        "Processed data not found.  "
        "Please run the pipeline first:\n\n"
        "```bash\n"
        "python run_pipeline.py\n"
        "```"
    )


def _show_image(filename: str, caption: str = ""):
    p = fig_path(filename)
    if p.exists():
        st.image(str(p), caption=caption, use_container_width=True)
    else:
        st.info(f"Figure not yet generated: {filename}")


# ── Tab 1: Data & Methodology ─────────────────────────────────────────────────

def tab_methodology():
    st.header("Data & Methodology")

    st.subheader("Problem statement")
    st.markdown(
        """
        Emergency healthcare access in Peru is profoundly unequal across its
        **1 874 districts**.  Geographic isolation, sparse infrastructure, and
        limited public investment leave many districts — particularly in rural
        Amazonia and the southern highlands — with almost no reachable emergency
        care.  This project builds a district-level *Emergency Healthcare Access
        Index* (EHAI) that integrates supply, utilisation, and spatial reach
        to rank districts by how well served their populations are.
        """
    )

    st.subheader("Data sources")
    st.markdown(
        """
        | Dataset | Source | Records (approx.) |
        |---|---|---|
        | IPRESS health facilities | MINSA / datosabiertos.gob.pe | ~22 000 |
        | Centros Poblados | INEI / datosabiertos.gob.pe | ~100 000 |
        | Emergency production C1 | SUSALUD / datos.susalud.gob.pe | varies by year |
        | District boundaries | d2cml-ai GitHub repo (DISTRITOS.shp) | 1 874 |
        """
    )

    st.subheader("Cleaning decisions")
    st.markdown(
        """
        **IPRESS**
        - Dropped rows with missing or out-of-Peru coordinates
          (lat ∉ [−20, 1] or lon ∉ [−82, −68]).
        - Retained only facilities marked as *active* (estado = ACTIVO).
        - Standardised UBIGEO codes to 6-character zero-padded strings.

        **Centros Poblados**
        - Same coordinate bounding-box filter.
        - De-duplicated by (ubigeo, nombre) to remove repeated records.

        **Emergencias (SUSALUD C1)**
        - Aggregated monthly records to district-level annual totals.
        - Joined with IPRESS clean table to recover missing UBIGEO codes.

        **Distritos shapefile**
        - Repaired invalid geometries with `buffer(0)` trick.
        - Ensured CRS = EPSG:4326 for consistent joining.
        """
    )

    st.subheader("Methodological decisions — EHAI construction")
    st.markdown(
        """
        The EHAI is a weighted composite of three normalised components:

        | Component | Definition | Why chosen |
        |---|---|---|
        | **A — Facility density** | Facilities per 10 000 population (baseline: all IPRESS; alternative: II/III level only) | Measures physical supply |
        | **B — Emergency activity** | Emergency consultations per 1 000 population | Measures actual utilisation |
        | **C — Spatial access** | % of populated centres within *d* km of nearest IPRESS | Measures geographic reachability |

        **Baseline**: equal weights (⅓ each), *d* = 5 km, any IPRESS category.

        **Alternative**: weights A=0.20, B=0.20, C=0.60; *d* = 10 km; only
        high-capacity (level II+) IPRESS.  This tests whether spatial access
        dominates the index and whether restricting to high-capacity facilities
        changes conclusions.

        Distance calculations use **EPSG:32718** (UTM Zone 18S) for metric
        accuracy across Peru.
        """
    )

    st.subheader("Limitations")
    st.markdown(
        """
        - **Population data**: district population is taken from the shapefile
          when available; otherwise density per km² is used — this understates
          access inequality in high-density urban districts.
        - **Travel time vs straight-line distance**: Euclidean distance
          ignores road networks and altitude barriers — real access in Andean
          districts is worse than the metric suggests.
        - **Temporal coverage**: emergency production data may not cover the
          same year as facility data; trends over time are not captured.
        - **Private facilities**: IPRESS from MINSA may undercount private
          providers, inflating apparent access in wealthier urban districts.
        """
    )


# ── Tab 2: Static Analysis ────────────────────────────────────────────────────

def tab_static():
    st.header("Static Analysis")
    gdf = load_metrics()
    if gdf is None:
        _pipeline_warning()
        return

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Districts analysed", len(gdf))
        if "n_facilities" in gdf.columns:
            st.metric("Total IPRESS facilities", int(gdf["n_facilities"].sum()))
        if "total_emergencias" in gdf.columns:
            st.metric("Total emergency consultations", f"{gdf['total_emergencias'].sum():,.0f}")
    with col2:
        if "ehai_base" in gdf.columns:
            st.metric("Avg EHAI (baseline)", f"{gdf['ehai_base'].mean():.3f}")
            st.metric("Median EHAI", f"{gdf['ehai_base'].median():.3f}")
        if "category_base" in gdf.columns:
            st.metric(
                "Underserved districts",
                (gdf["category_base"] == "Underserved").sum(),
            )

    st.divider()

    st.subheader("Chart 1 — EHAI Score Distribution")
    st.markdown(
        "A histogram is the right choice here because EHAI is a continuous variable. "
        "We want to see the shape of the distribution (skew, potential bimodality between "
        "urban and rural clusters) — a bar chart of counts by category would collapse that "
        "information and hide it."
    )
    _show_image("chart1_ehai_distribution.png")

    st.subheader("Chart 2 — Facility Supply vs Emergency Utilisation")
    st.markdown(
        "A scatter plot reveals whether high facility supply actually co-occurs with high "
        "utilisation.  Districts in the top-right quadrant are well-supplied *and* heavily "
        "used; those in the bottom-left are doubly disadvantaged.  A simple bar chart would "
        "not show this two-dimensional relationship."
    )
    _show_image("chart2_density_vs_activity.png")

    st.subheader("Chart 3 — Component Scores by Access Category")
    st.markdown(
        "Box plots show within-group variability and outliers — critical for validating "
        "that 'Underserved' districts truly score lower on *all* components, not just one. "
        "A grouped bar chart of means would mask wide within-group variance."
    )
    _show_image("chart3_component_boxplots.png")

    st.subheader("Chart 4 — Top and Bottom Districts")
    st.markdown(
        "Horizontal bar charts are the clearest way to rank a moderate number of named "
        "entities.  Showing both extremes in one figure directly answers Questions 1 and 3 "
        "without confusion."
    )
    _show_image("chart4_top_bottom_districts.png")

    st.subheader("Chart 5 — Sensitivity: Baseline vs Alternative Specification")
    st.markdown(
        "A scatter plot of baseline vs alternative EHAI scores is the most honest tool for "
        "communicating specification stability.  The Pearson correlation and distance from "
        "the 45° line both tell us how much rankings shift.  A table of rank changes would "
        "hide the systemic upward or downward shifts for certain district types."
    )
    _show_image("chart5_sensitivity.png")


# ── Tab 3: GeoSpatial Results ─────────────────────────────────────────────────

def tab_geospatial():
    st.header("GeoSpatial Results")
    gdf = load_metrics()
    if gdf is None:
        _pipeline_warning()
        return

    st.subheader("Map 1 — Choropleth: EHAI Baseline vs Alternative")
    st.markdown(
        "Choropleth maps reveal spatial clustering of access inequality — "
        "whether underserved districts are concentrated in specific regions "
        "(southern highlands, Amazonia) or distributed randomly."
    )
    _show_image("map1_ehai_choropleth.png")

    st.subheader("Map 2 — % Populated Centres within 5 km of any IPRESS")
    _show_image("map2_cp_access.png")

    st.subheader("District-level metrics table")
    drop_cols = ["geometry"]
    disp_df = pd.DataFrame(gdf.drop(columns=[c for c in drop_cols if c in gdf.columns]))

    # Show only key columns
    key_cols = [
        c for c in [
            "ubigeo", "distrito", "departamento",
            "n_facilities", "n_hicat_facilities",
            "n_centros_poblados", "pct_cp_within_5km", "pct_cp_within_10km",
            "total_emergencias", "ehai_base", "category_base",
            "ehai_alt", "category_alt",
        ]
        if c in disp_df.columns
    ]
    st.dataframe(
        disp_df[key_cols].sort_values("ehai_base", ascending=False).reset_index(drop=True)
        if "ehai_base" in disp_df.columns else disp_df,
        use_container_width=True,
    )

    st.subheader("Summary statistics by access category")
    if "category_base" in gdf.columns:
        numeric_cols = [c for c in ["ehai_base", "n_facilities", "pct_cp_within_5km", "total_emergencias"] if c in gdf.columns]
        summary = gdf.groupby("category_base")[numeric_cols].mean().round(3)
        cat_order = ["Underserved", "Moderate-Low", "Moderate-High", "Well-served"]
        summary = summary.reindex([c for c in cat_order if c in summary.index])
        st.dataframe(summary, use_container_width=True)


# ── Tab 4: Interactive Exploration ────────────────────────────────────────────

def tab_interactive():
    st.header("Interactive Exploration")
    gdf     = load_metrics()
    gdf_ip  = load_ipress()
    cmp     = load_comparison()

    if gdf is None:
        _pipeline_warning()
        return

    try:
        from streamlit_folium import st_folium
        from src.visualization import map_folium_interactive, map_folium_comparison
    except ImportError:
        st.error("Install `streamlit-folium` to see interactive maps.")
        return

    # ── Filters ───────────────────────────────────────────────────────────────
    dep_col = next((c for c in ["departamento", "dpto", "nom_dep"] if c in gdf.columns), None)
    if dep_col:
        deps = ["All"] + sorted(gdf[dep_col].dropna().unique().tolist())
        selected_dep = st.selectbox("Filter by department", deps)
        if selected_dep != "All":
            gdf_filt = gdf[gdf[dep_col] == selected_dep]
            gdf_ip_filt = gdf_ip[gdf_ip[dep_col] == selected_dep] if gdf_ip is not None and dep_col in gdf_ip.columns else gdf_ip
        else:
            gdf_filt, gdf_ip_filt = gdf, gdf_ip
    else:
        gdf_filt, gdf_ip_filt = gdf, gdf_ip

    st.subheader("Main map — EHAI choropleth + IPRESS facilities")
    with st.spinner("Rendering map..."):
        m = map_folium_interactive(gdf_filt, gdf_ip_filt)
        st_folium(m, width=1100, height=600, returned_objects=[])

    st.subheader("Baseline vs Alternative specification — map comparison")
    with st.spinner("Rendering comparison map..."):
        m2 = map_folium_comparison(gdf_filt)
        st_folium(m2, width=1100, height=500, returned_objects=[])

    # ── District explorer ─────────────────────────────────────────────────────
    st.subheader("District comparison tool")
    name_col = next((c for c in ["distrito", "nombre_distrito"] if c in gdf.columns), None)
    if name_col:
        districts = sorted(gdf[name_col].dropna().unique().tolist())
        selected = st.multiselect("Select districts to compare", districts, default=districts[:5])
        if selected:
            sub = gdf[gdf[name_col].isin(selected)]
            view_cols = [c for c in [
                name_col, dep_col, "ehai_base", "category_base", "ehai_alt", "category_alt",
                "n_facilities", "pct_cp_within_5km", "pct_cp_within_10km", "total_emergencias",
            ] if c and c in sub.columns]
            st.dataframe(pd.DataFrame(sub[view_cols]).reset_index(drop=True), use_container_width=True)

    # ── Sensitivity table ─────────────────────────────────────────────────────
    if cmp is not None:
        st.subheader("Specification sensitivity — full ranking comparison")
        st.markdown(
            "Districts where the baseline and alternative EHAI category differ are highlighted. "
            "A large `rank_change` means the district's position shifts substantially when "
            "the access definition changes — indicating it is sensitive to methodological choice."
        )

        def _highlight(row):
            colour = "background-color: #ffecb3" if row.get("category_shift", False) else ""
            return [colour] * len(row)

        st.dataframe(
            cmp.style.apply(_highlight, axis=1),
            use_container_width=True,
            height=400,
        )


# ── App entry-point ───────────────────────────────────────────────────────────

def main():
    st.title("Emergency Healthcare Access Inequality in Peru")
    st.caption(
        "A district-level geospatial analysis using IPRESS, Centros Poblados, "
        "Emergency Production (SUSALUD), and District Boundaries data."
    )

    tab1, tab2, tab3, tab4 = st.tabs([
        "📋 Data & Methodology",
        "📊 Static Analysis",
        "🗺️ GeoSpatial Results",
        "🔍 Interactive Exploration",
    ])

    with tab1:
        tab_methodology()
    with tab2:
        tab_static()
    with tab3:
        tab_geospatial()
    with tab4:
        tab_interactive()


if __name__ == "__main__":
    main()
