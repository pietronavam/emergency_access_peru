"""
geospatial.py — Spatial joins and distance logic.

CRS Strategy
------------
* All input data stored in EPSG:4326 (WGS-84 geographic).
* Distance calculations project to EPSG:32718 (UTM Zone 18S) — the metric
  CRS that minimises distortion for mainland Peru.
* Final outputs re-projected back to EPSG:4326 for Folium compatibility.

Key operations
--------------
1. Build GeoDataFrames for facilities and populated centres.
2. Spatial-join both to district polygons (assign ubigeo).
3. For each populated centre, compute distance to nearest IPRESS.
4. Classify whether centre is "within threshold" for baseline and alternative.
5. Build district-level summary table with facility counts, emergency totals,
   and spatial access fractions.
"""

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

from src.utils import (
    CRS_GEO,
    CRS_PROJ,
    DATA_PROC,
    DISTANCE_ALT_M,
    DISTANCE_BASELINE_M,
    HIGH_CAPACITY_CATEGORIES,
    find_col,
    get_logger,
)

log = get_logger("geospatial")


# ── GeoDataFrame builders ─────────────────────────────────────────────────────

def build_gdf_ipress(df: pd.DataFrame) -> gpd.GeoDataFrame:
    """Convert clean IPRESS DataFrame to GeoDataFrame."""
    lat = find_col(df, ["latitud", "lat", "latitude"])
    lon = find_col(df, ["longitud", "lon", "longitude"])
    geometry = gpd.points_from_xy(df[lon], df[lat])
    gdf = gpd.GeoDataFrame(df, geometry=geometry, crs=CRS_GEO)
    log.info("IPRESS GeoDataFrame: %d points", len(gdf))
    return gdf


def build_gdf_cp(df) -> gpd.GeoDataFrame:
    """Convert clean Centros Poblados (DataFrame or GeoDataFrame) to GeoDataFrame."""
    if isinstance(df, gpd.GeoDataFrame) and df.geometry.notna().any():
        gdf = df.to_crs(CRS_GEO)
        log.info("Centros Poblados GeoDataFrame (from shapefile): %d points", len(gdf))
        return gdf
    lat = find_col(df, ["latitud", "lat", "latitude", "Y"])
    lon = find_col(df, ["longitud", "lon", "longitude", "X"])
    geometry = gpd.points_from_xy(df[lon], df[lat])
    gdf = gpd.GeoDataFrame(df, geometry=geometry, crs=CRS_GEO)
    log.info("Centros Poblados GeoDataFrame: %d points", len(gdf))
    return gdf


# ── Spatial joins ─────────────────────────────────────────────────────────────

def join_points_to_districts(
    gdf_points: gpd.GeoDataFrame,
    gdf_districts: gpd.GeoDataFrame,
    point_label: str = "points",
) -> gpd.GeoDataFrame:
    """
    Spatial join: assign each point to its containing district polygon.
    Points outside all polygons are assigned via nearest-district fallback.
    """
    log.info("Joining %s to districts...", point_label)

    pts  = gdf_points.to_crs(CRS_GEO)
    dist = gdf_districts.to_crs(CRS_GEO)

    # Ensure districts have ubigeo
    ubigeo_col = find_col(dist, ["ubigeo", "cod_ubigeo", "ubigeo_inei"], required=False)
    if ubigeo_col and ubigeo_col != "ubigeo":
        dist = dist.rename(columns={ubigeo_col: "ubigeo"})

    joined = gpd.sjoin(pts, dist[["ubigeo", "geometry"]], how="left", predicate="within")
    joined = joined.rename(columns={"ubigeo_right": "ubigeo_dist"}) if "ubigeo_right" in joined.columns else joined

    # Fallback for points outside all polygons (islands, border artefacts)
    missing_mask = joined["ubigeo"].isna() if "ubigeo" in joined.columns else joined["ubigeo_dist"].isna()
    if missing_mask.sum() > 0:
        log.info("  %d %s outside polygon — using nearest-district fallback.", missing_mask.sum(), point_label)
        pts_miss  = pts[missing_mask].to_crs(CRS_PROJ)
        dist_proj = dist.to_crs(CRS_PROJ)
        nearest   = gpd.sjoin_nearest(pts_miss, dist_proj[["ubigeo", "geometry"]], how="left")
        ub_col_near = "ubigeo_right" if "ubigeo_right" in nearest.columns else "ubigeo"
        joined.loc[missing_mask, "ubigeo"] = nearest[ub_col_near].values

    assigned = (~joined["ubigeo"].isna()).sum() if "ubigeo" in joined.columns else "?"
    log.info("  %s: %s/%d assigned to a district.", point_label, assigned, len(pts))
    return joined


# ── Distance from Centros Poblados to nearest IPRESS ─────────────────────────

def compute_nearest_facility_distance(
    gdf_cp: gpd.GeoDataFrame,
    gdf_ipress: gpd.GeoDataFrame,
    ipress_subset: gpd.GeoDataFrame | None = None,
) -> pd.DataFrame:
    """
    For each populated centre, compute distance (metres) to nearest IPRESS
    in the full set and in the high-capacity subset.

    Returns a DataFrame with columns:
        dist_nearest_any_m      — distance to any IPRESS
        dist_nearest_hicat_m    — distance to high-capacity IPRESS (may be NaN)
    """
    log.info("Computing nearest-facility distances for %d centres...", len(gdf_cp))

    cp_proj = gdf_cp.to_crs(CRS_PROJ)[["geometry"]].copy()
    ip_proj = gdf_ipress.to_crs(CRS_PROJ)[["geometry", "categoria"]].copy() if "categoria" in gdf_ipress.columns else gdf_ipress.to_crs(CRS_PROJ)[["geometry"]].copy()

    # Distance to nearest ANY facility
    nearest_any = gpd.sjoin_nearest(
        cp_proj, ip_proj[["geometry"]], how="left", distance_col="dist_nearest_any_m"
    )
    # sjoin_nearest may produce duplicates if multiple equidistant matches exist
    nearest_any = nearest_any[~nearest_any.index.duplicated(keep="first")]

    result = gdf_cp[[]].copy()  # empty DF with same index
    result["dist_nearest_any_m"] = nearest_any["dist_nearest_any_m"]

    # Distance to nearest HIGH-CAPACITY facility
    if "categoria" in ip_proj.columns:
        ip_hicat = ip_proj[ip_proj["categoria"].isin(HIGH_CAPACITY_CATEGORIES)]
        if len(ip_hicat) > 0:
            nearest_hi = gpd.sjoin_nearest(
                cp_proj, ip_hicat[["geometry"]], how="left", distance_col="dist_nearest_hicat_m"
            )
            nearest_hi = nearest_hi[~nearest_hi.index.duplicated(keep="first")]
            result["dist_nearest_hicat_m"] = nearest_hi["dist_nearest_hicat_m"]
        else:
            result["dist_nearest_hicat_m"] = np.nan
    else:
        result["dist_nearest_hicat_m"] = result["dist_nearest_any_m"]

    log.info("  Distance stats (any facility): median=%.0f m, max=%.0f m",
             result["dist_nearest_any_m"].median(), result["dist_nearest_any_m"].max())
    return result


# ── District-level access summary ─────────────────────────────────────────────

def build_district_access_table(
    gdf_cp_with_dist: gpd.GeoDataFrame,
    gdf_ipress_with_ubigeo: gpd.GeoDataFrame,
    df_emergencias: pd.DataFrame,
    gdf_districts: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """
    Aggregate all spatial information to district level.

    Returns a GeoDataFrame with one row per district and columns:
        ubigeo, district-name columns, geometry,
        n_facilities, n_hicat_facilities,
        n_centros_poblados, pct_cp_within_5km, pct_cp_within_10km,
        pct_cp_hicat_within_5km, pct_cp_hicat_within_10km,
        total_emergencias,
        poblacion (if available)
    """
    log.info("Building district-level access table...")

    # ── 1. Facility counts per district ──────────────────────────────────────
    ip = gdf_ipress_with_ubigeo.copy()

    # Determine ubigeo column in joined ipress
    ub_col = find_col(ip, ["ubigeo", "ubigeo_dist"], required=False) or "ubigeo"
    if ub_col not in ip.columns and "ubigeo_right" in ip.columns:
        ip["ubigeo"] = ip["ubigeo_right"]
        ub_col = "ubigeo"

    fac_counts = ip.groupby(ub_col).agg(
        n_facilities=("geometry", "count"),
    ).reset_index().rename(columns={ub_col: "ubigeo"})

    if "categoria" in ip.columns:
        hicat = ip[ip["categoria"].isin(HIGH_CAPACITY_CATEGORIES)]
        hicat_counts = hicat.groupby(ub_col).size().reset_index(name="n_hicat_facilities")
        hicat_counts.rename(columns={ub_col: "ubigeo"}, inplace=True)
        fac_counts = fac_counts.merge(hicat_counts, on="ubigeo", how="left")
        fac_counts["n_hicat_facilities"] = fac_counts["n_hicat_facilities"].fillna(0).astype(int)
    else:
        fac_counts["n_hicat_facilities"] = fac_counts["n_facilities"]

    # ── 2. Populated-centre access fractions per district ─────────────────────
    cp = gdf_cp_with_dist.copy()
    ub_col_cp = find_col(cp, ["ubigeo", "ubigeo_dist"], required=False)
    if ub_col_cp and ub_col_cp != "ubigeo":
        cp["ubigeo"] = cp[ub_col_cp]

    if "dist_nearest_any_m" not in cp.columns:
        cp["dist_nearest_any_m"] = np.nan
    if "dist_nearest_hicat_m" not in cp.columns:
        cp["dist_nearest_hicat_m"] = cp["dist_nearest_any_m"]

    cp["within_5km"]       = cp["dist_nearest_any_m"]  <= DISTANCE_BASELINE_M
    cp["within_10km"]      = cp["dist_nearest_any_m"]  <= DISTANCE_ALT_M
    cp["hicat_within_5km"] = cp["dist_nearest_hicat_m"] <= DISTANCE_BASELINE_M
    cp["hicat_within_10km"]= cp["dist_nearest_hicat_m"] <= DISTANCE_ALT_M

    def pct(x):
        return 100 * x.sum() / len(x) if len(x) > 0 else np.nan

    cp_agg = cp.groupby("ubigeo").agg(
        n_centros_poblados=("within_5km", "count"),
        pct_cp_within_5km =("within_5km",  pct),
        pct_cp_within_10km=("within_10km", pct),
        pct_cp_hicat_within_5km =("hicat_within_5km",  pct),
        pct_cp_hicat_within_10km=("hicat_within_10km", pct),
    ).reset_index()

    # ── 3. Emergency totals per district ──────────────────────────────────────
    emerg = df_emergencias.copy()
    ub_emerg = find_col(emerg, ["ubigeo", "ubigeo_dist"], required=False)
    if ub_emerg:
        if ub_emerg != "ubigeo":
            emerg["ubigeo"] = emerg[ub_emerg]
        emerg_agg = emerg.groupby("ubigeo")["total_emergencias"].sum().reset_index()
    else:
        emerg_agg = pd.DataFrame(columns=["ubigeo", "total_emergencias"])

    # ── 4. Merge everything onto district polygons ────────────────────────────
    dist = gdf_districts.to_crs(CRS_GEO).copy()
    ub_dist = find_col(dist, ["ubigeo", "cod_ubigeo"], required=False) or "ubigeo"
    if ub_dist != "ubigeo":
        dist["ubigeo"] = dist[ub_dist]

    result = dist.merge(fac_counts,  on="ubigeo", how="left")
    result = result.merge(cp_agg,    on="ubigeo", how="left")
    result = result.merge(emerg_agg, on="ubigeo", how="left")

    result["n_facilities"]         = result["n_facilities"].fillna(0).astype(int)
    result["n_hicat_facilities"]   = result.get("n_hicat_facilities", pd.Series(0)).fillna(0).astype(int)
    result["n_centros_poblados"]   = result["n_centros_poblados"].fillna(0).astype(int)
    result["total_emergencias"]    = result["total_emergencias"].fillna(0)
    result["pct_cp_within_5km"]    = result["pct_cp_within_5km"].fillna(0)
    result["pct_cp_within_10km"]   = result["pct_cp_within_10km"].fillna(0)
    result["pct_cp_hicat_within_5km"]  = result.get("pct_cp_hicat_within_5km", pd.Series(np.nan)).fillna(0)
    result["pct_cp_hicat_within_10km"] = result.get("pct_cp_hicat_within_10km", pd.Series(np.nan)).fillna(0)

    log.info("District access table: %d rows", len(result))

    out = DATA_PROC / "district_access_raw.geojson"
    result.to_file(out, driver="GeoJSON")
    log.info("Saved → %s", out)
    return result


# ── Master builder ────────────────────────────────────────────────────────────

def build_geospatial_pipeline(cleaned: dict) -> gpd.GeoDataFrame:
    """
    Full geospatial pipeline from cleaned data to district access table.

    Parameters
    ----------
    cleaned : dict with 'ipress', 'centros_poblados', 'emergencias', 'distritos'

    Returns
    -------
    GeoDataFrame with district-level spatial access data
    """
    gdf_ipress = build_gdf_ipress(cleaned["ipress"])
    gdf_cp     = build_gdf_cp(cleaned["centros_poblados"])
    gdf_dist   = cleaned["distritos"]

    # Assign facilities to districts
    gdf_ipress_dist = join_points_to_districts(gdf_ipress, gdf_dist, "IPRESS")

    # Assign CP to districts
    gdf_cp_dist = join_points_to_districts(gdf_cp, gdf_dist, "CentrosPoblados")

    # Compute distances
    dist_df = compute_nearest_facility_distance(gdf_cp_dist, gdf_ipress)
    gdf_cp_with_dist = gdf_cp_dist.copy()
    gdf_cp_with_dist["dist_nearest_any_m"]  = dist_df["dist_nearest_any_m"].values
    gdf_cp_with_dist["dist_nearest_hicat_m"]= dist_df.get("dist_nearest_hicat_m", dist_df["dist_nearest_any_m"]).values

    # Build district-level table
    district_table = build_district_access_table(
        gdf_cp_with_dist,
        gdf_ipress_dist,
        cleaned["emergencias"],
        gdf_dist,
    )

    return district_table
