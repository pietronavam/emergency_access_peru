"""
visualization.py — Static charts (matplotlib / seaborn) and maps (GeoPandas / Folium).

Chart selection rationale
-------------------------
Chart 1  — Histogram of EHAI scores
    Chosen to show the distribution shape and detect skew/bimodality — a bar
    chart of counts would obscure the continuous nature of the index.

Chart 2  — Scatter: facility density vs emergency activity (coloured by category)
    Chosen over a simple bar chart because it reveals whether high supply
    coincides with high utilisation — key to distinguishing access types.

Chart 3  — Box-plot: EHAI components by quartile category
    Chosen to show within-group variability, not just means — essential when
    claiming that one group is "different" from another.

Chart 4  — Bar: top/bottom 20 districts by EHAI (baseline)
    Chosen as the clearest direct answer to Q1 and Q3 without confusion.

Chart 5  — Scatter: EHAI baseline vs alternative (sensitivity)
    Chosen to visualise how much rankings shift between specifications —
    a correlation plot is the most honest way to communicate stability.

Map 1  (static) — Choropleth of EHAI baseline
Map 2  (static) — Choropleth of % CP within 5 km
Map 3  (Folium) — Interactive layered map with facility markers + choropleth
"""

from pathlib import Path

import folium
import geopandas as gpd
import matplotlib
import matplotlib.cm as cm
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from branca.colormap import linear
from folium.plugins import MarkerCluster

from src.utils import OUTPUT_FIGS, CRS_GEO, find_col, get_logger

matplotlib.use("Agg")  # non-interactive backend for headless runs
log = get_logger("visualization")

sns.set_theme(style="whitegrid", palette="muted", font_scale=1.1)

PALETTE = {
    "Underserved":    "#d62728",
    "Moderate-Low":   "#ff7f0e",
    "Moderate-High":  "#2ca02c",
    "Well-served":    "#1f77b4",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _save(fig, name: str, dpi: int = 150):
    out = OUTPUT_FIGS / name
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    log.info("Saved figure → %s", out)
    return out


def _col(df, candidates, default=None):
    try:
        return find_col(df, candidates)
    except KeyError:
        return default


# ── Chart 1: EHAI distribution ────────────────────────────────────────────────

def chart_ehai_distribution(gdf: gpd.GeoDataFrame) -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for ax, col, title in zip(
        axes,
        ["ehai_base", "ehai_alt"],
        ["Baseline EHAI (equal weights, 5 km)", "Alternative EHAI (access 60%, 10 km / high-cap)"],
    ):
        if col not in gdf.columns:
            continue
        ax.hist(gdf[col].dropna(), bins=40, color="#4878d0", edgecolor="white", alpha=0.85)
        ax.axvline(gdf[col].median(), color="#dd2222", linewidth=1.5, linestyle="--", label=f"Median {gdf[col].median():.3f}")
        ax.set_xlabel("EHAI score (0 = worst, 1 = best)")
        ax.set_ylabel("Number of districts")
        ax.set_title(title)
        ax.legend()
    fig.suptitle("Distribution of Emergency Healthcare Access Index across Peruvian Districts", y=1.02)
    return _save(fig, "chart1_ehai_distribution.png")


# ── Chart 2: Facility density vs Emergency activity ───────────────────────────

def chart_density_vs_activity(gdf: gpd.GeoDataFrame) -> Path:
    comp_f = _col(gdf, ["comp_facility_base"], "comp_facility_base")
    comp_e = _col(gdf, ["comp_emergency_base"], "comp_emergency_base")
    cat    = _col(gdf, ["category_base"], "category_base")

    if not all(c in gdf.columns for c in [comp_f, comp_e]):
        log.warning("chart2: required columns missing, skipping.")
        return None

    df = pd.DataFrame(gdf[[comp_f, comp_e, cat]].dropna())
    df.columns = ["facility", "emergency", "category"]

    fig, ax = plt.subplots(figsize=(9, 6))
    for cat_val, colour in PALETTE.items():
        sub = df[df["category"] == cat_val]
        ax.scatter(sub["facility"], sub["emergency"], label=cat_val, color=colour, alpha=0.65, s=30)
    ax.set_xlabel("Facility density component (normalised)")
    ax.set_ylabel("Emergency activity component (normalised)")
    ax.set_title("Facility Supply vs Emergency Utilisation by District")
    ax.legend(title="EHAI Category")
    return _save(fig, "chart2_density_vs_activity.png")


# ── Chart 3: Box-plot of components by category ───────────────────────────────

def chart_component_boxplots(gdf: gpd.GeoDataFrame) -> Path:
    comp_cols = [c for c in ["comp_facility_base", "comp_emergency_base", "comp_access_base"] if c in gdf.columns]
    cat_col   = _col(gdf, ["category_base"])
    if not comp_cols or cat_col not in gdf.columns:
        log.warning("chart3: required columns missing, skipping.")
        return None

    label_map = {
        "comp_facility_base": "Facility\nDensity",
        "comp_emergency_base": "Emergency\nActivity",
        "comp_access_base": "Spatial\nAccess",
    }
    long = gdf[comp_cols + [cat_col]].melt(id_vars=cat_col, var_name="Component", value_name="Score")
    long["Component"] = long["Component"].map(label_map)

    order = ["Underserved", "Moderate-Low", "Moderate-High", "Well-served"]
    order = [o for o in order if o in long[cat_col].unique()]

    fig, ax = plt.subplots(figsize=(11, 6))
    sns.boxplot(
        data=long, x="Component", y="Score", hue=cat_col,
        hue_order=order, palette=PALETTE, ax=ax, linewidth=0.8,
    )
    ax.set_title("EHAI Component Scores by District Access Category")
    ax.set_xlabel("")
    ax.set_ylabel("Normalised score")
    ax.legend(title="Category", bbox_to_anchor=(1.01, 1), loc="upper left")
    return _save(fig, "chart3_component_boxplots.png")


# ── Chart 4: Top / Bottom 20 districts ────────────────────────────────────────

def chart_top_bottom_districts(gdf: gpd.GeoDataFrame, n: int = 20) -> Path:
    score_col = "ehai_base" if "ehai_base" in gdf.columns else gdf.columns[-1]
    name_col  = _col(gdf, ["distrito", "nombre_distrito", "dist", "nombdist"], default=None)

    df = pd.DataFrame(gdf[[score_col] + ([name_col] if name_col else [])].dropna(subset=[score_col]))
    df["label"] = df[name_col].str[:30] if name_col else df.index.astype(str)

    top  = df.nlargest(n, score_col)
    bot  = df.nsmallest(n, score_col)

    fig, axes = plt.subplots(1, 2, figsize=(14, 8), sharey=False)
    for ax, sub, title, colour in zip(
        axes,
        [top, bot],
        [f"Top {n} Best-served Districts", f"Top {n} Most Underserved Districts"],
        ["#1f77b4", "#d62728"],
    ):
        sub_sorted = sub.sort_values(score_col, ascending=(colour == "#d62728"))
        ax.barh(sub_sorted["label"], sub_sorted[score_col], color=colour, alpha=0.8)
        ax.set_xlabel("EHAI Score (baseline)")
        ax.set_title(title)
        ax.invert_yaxis()
    fig.suptitle("Districts at the Extremes of Emergency Healthcare Access")
    plt.tight_layout()
    return _save(fig, "chart4_top_bottom_districts.png")


# ── Chart 5: Baseline vs Alternative sensitivity ──────────────────────────────

def chart_sensitivity(gdf: gpd.GeoDataFrame) -> Path:
    if "ehai_base" not in gdf.columns or "ehai_alt" not in gdf.columns:
        log.warning("chart5: sensitivity columns missing, skipping.")
        return None

    df = pd.DataFrame(gdf[["ehai_base", "ehai_alt", "category_base"]].dropna())

    corr = df["ehai_base"].corr(df["ehai_alt"])
    fig, ax = plt.subplots(figsize=(8, 6))
    for cat_val, colour in PALETTE.items():
        sub = df[df["category_base"] == cat_val]
        ax.scatter(sub["ehai_base"], sub["ehai_alt"], label=cat_val, color=colour, alpha=0.6, s=25)
    ax.plot([0, 1], [0, 1], "k--", linewidth=1, alpha=0.5, label="No change line")
    ax.set_xlabel("EHAI — Baseline")
    ax.set_ylabel("EHAI — Alternative")
    ax.set_title(f"Specification Sensitivity (Pearson r = {corr:.3f})")
    ax.legend(title="Baseline Category")
    return _save(fig, "chart5_sensitivity.png")


# ── Static map 1: EHAI choropleth ─────────────────────────────────────────────

def map_ehai_static(gdf: gpd.GeoDataFrame) -> Path:
    score_col = "ehai_base" if "ehai_base" in gdf.columns else None
    if score_col is None:
        return None

    fig, axes = plt.subplots(1, 2, figsize=(18, 10))
    for ax, col, title in zip(
        axes,
        ["ehai_base", "ehai_alt"],
        ["Baseline EHAI", "Alternative EHAI"],
    ):
        if col not in gdf.columns:
            continue
        gdf.plot(
            column=col, ax=ax, cmap="RdYlGn",
            legend=True, missing_kwds={"color": "lightgrey"},
            legend_kwds={"label": "EHAI Score", "shrink": 0.6},
            linewidth=0.1, edgecolor="white",
        )
        ax.set_title(title, fontsize=14)
        ax.axis("off")
    fig.suptitle("Emergency Healthcare Access Index — Peru Districts", fontsize=16, y=0.98)
    return _save(fig, "map1_ehai_choropleth.png", dpi=150)


# ── Static map 2: % CP within 5 km ───────────────────────────────────────────

def map_cp_access_static(gdf: gpd.GeoDataFrame) -> Path:
    col = "pct_cp_within_5km" if "pct_cp_within_5km" in gdf.columns else None
    if col is None:
        return None

    fig, ax = plt.subplots(figsize=(10, 12))
    gdf.plot(
        column=col, ax=ax, cmap="YlOrRd",
        legend=True, missing_kwds={"color": "lightgrey"},
        legend_kwds={"label": "% CP within 5 km", "shrink": 0.6},
        linewidth=0.1, edgecolor="white",
    )
    ax.set_title("Populated Centres within 5 km of any IPRESS (% per district)", fontsize=13)
    ax.axis("off")
    return _save(fig, "map2_cp_access.png", dpi=150)


# ── Folium interactive map ────────────────────────────────────────────────────

def map_folium_interactive(
    gdf_districts: gpd.GeoDataFrame,
    gdf_ipress: gpd.GeoDataFrame | None = None,
    score_col: str = "ehai_base",
) -> folium.Map:
    """
    Build an interactive Folium map with:
    - Choropleth layer for EHAI score
    - MarkerCluster layer for IPRESS facilities
    Returns the folium.Map object (caller handles saving/display).
    """
    gdf = gdf_districts.to_crs(CRS_GEO)

    # Centre on Peru
    center = [-9.19, -75.0]
    m = folium.Map(location=center, zoom_start=6, tiles="CartoDB positron")

    # ── Choropleth ────────────────────────────────────────────────────────────
    if score_col in gdf.columns:
        # Use GeoJson with style_function for GeoDataFrame
        col_vals = gdf[score_col].fillna(0)
        vmin, vmax = col_vals.min(), col_vals.max()
        colormap = linear.RdYlGn_09.scale(vmin, vmax)
        colormap.caption = f"EHAI Score ({score_col})"

        def style_function(feature):
            val = feature["properties"].get(score_col, 0) or 0
            return {
                "fillColor": colormap(val),
                "color": "white",
                "weight": 0.3,
                "fillOpacity": 0.7,
            }

        name_col = find_col(gdf, ["distrito", "nombre_distrito", "dist"], required=False)
        tooltip_fields = [f for f in [score_col, name_col, "n_facilities", "total_emergencias"] if f and f in gdf.columns]
        tooltip_aliases = {score_col: "EHAI:", name_col: "Distrito:", "n_facilities": "Facilities:", "total_emergencias": "Emergencies:"}

        folium.GeoJson(
            gdf.__geo_interface__,
            name="EHAI (baseline)",
            style_function=style_function,
            tooltip=folium.GeoJsonTooltip(
                fields=tooltip_fields,
                aliases=[tooltip_aliases.get(f, f) for f in tooltip_fields],
                localize=True,
            ),
        ).add_to(m)
        colormap.add_to(m)

    # ── IPRESS markers ────────────────────────────────────────────────────────
    if gdf_ipress is not None and len(gdf_ipress) > 0:
        ip = gdf_ipress.to_crs(CRS_GEO)
        cluster = MarkerCluster(name="IPRESS facilities").add_to(m)
        lat_col = find_col(ip, ["latitud", "lat"], required=False)
        lon_col = find_col(ip, ["longitud", "lon"], required=False)
        nom_col = find_col(ip, ["nombre", "nombre_ipress"], required=False)
        cat_col = find_col(ip, ["categoria"], required=False)

        for _, row in ip.iterrows():
            lat = row[lat_col] if lat_col else row.geometry.y
            lon = row[lon_col] if lon_col else row.geometry.x
            if pd.isna(lat) or pd.isna(lon):
                continue
            popup_text = (
                f"<b>{row[nom_col] if nom_col else 'IPRESS'}</b><br>"
                f"Categoría: {row[cat_col] if cat_col else 'N/A'}"
            )
            folium.CircleMarker(
                location=[lat, lon],
                radius=4,
                color="#1f77b4",
                fill=True,
                fill_opacity=0.7,
                popup=folium.Popup(popup_text, max_width=200),
            ).add_to(cluster)

    folium.LayerControl().add_to(m)
    return m


def map_folium_comparison(gdf: gpd.GeoDataFrame) -> folium.Map:
    """Side-by-side colour comparison using two GeoJson layers."""
    g = gdf.to_crs(CRS_GEO)
    center = [-9.19, -75.0]
    m = folium.Map(location=center, zoom_start=6, tiles="CartoDB positron")

    for col, name in [("ehai_base", "Baseline EHAI"), ("ehai_alt", "Alternative EHAI")]:
        if col not in g.columns:
            continue
        vals = g[col].fillna(0)
        cm_obj = linear.RdYlGn_09.scale(vals.min(), vals.max())

        def _style(feat, _col=col, _cm=cm_obj):
            v = feat["properties"].get(_col, 0) or 0
            return {"fillColor": _cm(v), "color": "white", "weight": 0.2, "fillOpacity": 0.65}

        folium.GeoJson(g.__geo_interface__, name=name, style_function=_style, show=(col == "ehai_base")).add_to(m)

    folium.LayerControl().add_to(m)
    return m


# ── Master function ────────────────────────────────────────────────────────────

def generate_all_visuals(
    gdf_metrics: gpd.GeoDataFrame,
    gdf_ipress: gpd.GeoDataFrame | None = None,
) -> dict:
    """Generate all static and interactive visualisations. Returns dict of paths/maps."""
    out = {}
    out["chart1"] = chart_ehai_distribution(gdf_metrics)
    out["chart2"] = chart_density_vs_activity(gdf_metrics)
    out["chart3"] = chart_component_boxplots(gdf_metrics)
    out["chart4"] = chart_top_bottom_districts(gdf_metrics)
    out["chart5"] = chart_sensitivity(gdf_metrics)
    out["map1"]   = map_ehai_static(gdf_metrics)
    out["map2"]   = map_cp_access_static(gdf_metrics)
    out["folium_main"]       = map_folium_interactive(gdf_metrics, gdf_ipress)
    out["folium_comparison"] = map_folium_comparison(gdf_metrics)
    log.info("All visuals generated.")
    return out
