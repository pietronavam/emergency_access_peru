"""
metrics.py — District-level composite access index.

Methodology
-----------
We construct a composite Emergency Healthcare Access Index (EHAI) at the
district level from three equally-observable components:

  Component A – Facility Density
      facilities per 10 000 population (or per km² if population unknown).
      Captures physical supply of health infrastructure.

  Component B – Emergency Activity
      total emergency consultations per 1 000 population (or absolute if
      population unknown).  Captures actual utilisation of emergency services.

  Component C – Spatial Access
      fraction of populated centres within a threshold distance of any IPRESS.
      Captures whether the population *can reach* a facility.

Each component is min-max normalised to [0, 1] across districts.

Baseline specification
    Equal weights (1/3 each); distance threshold = 5 km; any IPRESS.

Alternative specification
    Facility and emergency components re-weighted to 0.20 each (spatial
    access weighted 0.60); distance threshold = 10 km; high-capacity IPRESS
    only.  This tests sensitivity to access definition and facility type.

Districts are then classified into quartiles (underserved / moderate-low /
moderate-high / well-served) based on the composite score.
"""

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from src.utils import (
    DATA_PROC,
    OUTPUT_TABS,
    WEIGHTS_ALT,
    WEIGHTS_BASELINE,
    get_logger,
    find_col,
)

log = get_logger("metrics")


# ── Normalisation ─────────────────────────────────────────────────────────────

def minmax(series: pd.Series) -> pd.Series:
    """Min-max normalise a series to [0, 1]; constant series → 0.5."""
    lo, hi = series.min(), series.max()
    if hi == lo:
        return pd.Series(0.5, index=series.index)
    return (series - lo) / (hi - lo)


# ── Component A: Facility density ─────────────────────────────────────────────

def _facility_density(gdf: gpd.GeoDataFrame, n_col: str = "n_facilities") -> pd.Series:
    """
    Facilities per 10 000 population.  Falls back to facilities per km²
    if population is unavailable.
    """
    pop_col = find_col(gdf, ["poblacion", "pob_total", "pob"], required=False)
    if pop_col and gdf[pop_col].sum() > 0:
        density = gdf[n_col] / (gdf[pop_col].replace(0, np.nan) / 10_000)
    else:
        # Compute area in km²
        area_km2 = gdf.to_crs("EPSG:32718").geometry.area / 1e6
        density = gdf[n_col] / area_km2.replace(0, np.nan)
        log.info("  Population not available — using facility density per km².")
    return density.fillna(0)


# ── Component B: Emergency activity ──────────────────────────────────────────

def _emergency_activity(gdf: gpd.GeoDataFrame) -> pd.Series:
    """Emergency consultations per 1 000 population (or absolute)."""
    pop_col = find_col(gdf, ["poblacion", "pob_total", "pob"], required=False)
    if pop_col and gdf[pop_col].sum() > 0:
        rate = gdf["total_emergencias"] / (gdf[pop_col].replace(0, np.nan) / 1_000)
    else:
        rate = gdf["total_emergencias"].astype(float)
        log.info("  Population not available — using absolute emergency counts.")
    return rate.fillna(0)


# ── Composite index ───────────────────────────────────────────────────────────

def compute_composite(
    gdf: gpd.GeoDataFrame,
    spec: str = "baseline",
) -> gpd.GeoDataFrame:
    """
    Add normalised components and composite EHAI score to district GeoDataFrame.

    Parameters
    ----------
    gdf  : district GeoDataFrame from geospatial pipeline
    spec : 'baseline' or 'alternative'

    Returns
    -------
    GeoDataFrame with added component and score columns
    """
    g = gdf.copy()

    if spec == "baseline":
        weights     = WEIGHTS_BASELINE
        access_col  = "pct_cp_within_5km"
        fac_col     = "n_facilities"
        suffix      = "_base"
    else:
        weights     = WEIGHTS_ALT
        access_col  = "pct_cp_hicat_within_10km"
        fac_col     = "n_hicat_facilities"
        suffix      = "_alt"

    # Ensure access column exists
    if access_col not in g.columns:
        fallback = "pct_cp_within_5km" if spec == "baseline" else "pct_cp_within_10km"
        access_col = fallback if fallback in g.columns else g.columns[-1]
        log.warning("  '%s' not found, using '%s' for %s.", access_col, fallback, spec)

    # Raw components
    comp_a_raw = _facility_density(g, fac_col)
    comp_b_raw = _emergency_activity(g)
    comp_c_raw = g[access_col].fillna(0)

    # Normalised
    g[f"comp_facility{suffix}"] = minmax(comp_a_raw)
    g[f"comp_emergency{suffix}"]= minmax(comp_b_raw)
    g[f"comp_access{suffix}"]   = minmax(comp_c_raw)

    # Weighted composite
    g[f"ehai{suffix}"] = (
        weights["facilities"] * g[f"comp_facility{suffix}"] +
        weights["emergency"]  * g[f"comp_emergency{suffix}"] +
        weights["access"]     * g[f"comp_access{suffix}"]
    )

    # Quartile classification (robust to ties / few unique values)
    all_labels = ["Underserved", "Moderate-Low", "Moderate-High", "Well-served"]
    for q in [4, 3, 2]:
        try:
            labels = all_labels[:q]
            g[f"category{suffix}"] = pd.qcut(
                g[f"ehai{suffix}"], q=q, labels=labels, duplicates="drop"
            ).astype(str)
            break
        except ValueError:
            continue
    else:
        median = g[f"ehai{suffix}"].median()
        g[f"category{suffix}"] = g[f"ehai{suffix}"].apply(
            lambda x: "Well-served" if x >= median else "Underserved"
        )

    log.info("  %s EHAI — mean=%.3f  std=%.3f", spec, g[f"ehai{suffix}"].mean(), g[f"ehai{suffix}"].std())
    return g


# ── Sensitivity comparison ────────────────────────────────────────────────────

def compare_specifications(gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    """
    Return a DataFrame showing how districts shift between quartiles
    when moving from baseline to alternative specification.
    """
    if "ehai_base" not in gdf.columns or "ehai_alt" not in gdf.columns:
        raise ValueError("Run compute_composite for both specs first.")

    ub_col    = find_col(gdf, ["ubigeo"], required=False) or gdf.index.name or "index"
    name_col  = find_col(gdf, ["distrito", "nombre_distrito"], required=False)

    cols = [ub_col] if ub_col in gdf.columns else []
    if name_col:
        cols.append(name_col)
    cols += ["ehai_base", "category_base", "ehai_alt", "category_alt"]
    cols  = [c for c in cols if c in gdf.columns]

    cmp = gdf[cols].copy()
    cmp["ehai_change"]    = cmp["ehai_alt"] - cmp["ehai_base"]
    cmp["rank_base"]      = cmp["ehai_base"].rank(ascending=False).astype(int)
    cmp["rank_alt"]       = cmp["ehai_alt"].rank(ascending=False).astype(int)
    cmp["rank_change"]    = cmp["rank_base"] - cmp["rank_alt"]
    cmp["category_shift"] = cmp["category_base"] != cmp["category_alt"]

    n_shifts = cmp["category_shift"].sum()
    log.info("  %d/%d districts changed category between specifications.", n_shifts, len(cmp))
    return cmp.sort_values("ehai_base", ascending=False).reset_index(drop=True)


# ── Run all ───────────────────────────────────────────────────────────────────

def compute_all_metrics(gdf_district_access: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Compute baseline and alternative EHAI, add sensitivity comparison.
    Saves final tables to output/tables/.

    Returns enriched GeoDataFrame.
    """
    gdf = compute_composite(gdf_district_access, spec="baseline")
    gdf = compute_composite(gdf, spec="alternative")

    # Save full district metrics
    out_csv  = OUTPUT_TABS / "district_metrics.csv"
    out_geo  = DATA_PROC   / "district_metrics.geojson"

    # Drop geometry for CSV
    df_csv = pd.DataFrame(gdf.drop(columns="geometry"))
    df_csv.to_csv(out_csv, index=False)
    log.info("Saved district metrics CSV → %s", out_csv)

    gdf.to_file(out_geo, driver="GeoJSON")
    log.info("Saved district metrics GeoJSON → %s", out_geo)

    # Sensitivity comparison table
    cmp = compare_specifications(gdf)
    cmp.to_csv(OUTPUT_TABS / "specification_comparison.csv", index=False)
    log.info("Saved specification comparison → %s", OUTPUT_TABS / 'specification_comparison.csv')

    return gdf
