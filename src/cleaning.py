"""
cleaning.py — Standardize, validate, and save clean versions of all datasets.

Cleaning decisions
------------------
* IPRESS        : drop rows with missing coordinates; standardize ubigeo to 6-char;
                  keep only active facilities.
* Centros Poblados: drop rows with missing coords; deduplicate by ubigeo+name.
* Emergencias   : aggregate monthly records to annual district-level totals;
                  join with IPRESS to get district ubigeo.
* Distritos     : normalize ubigeo; repair geometry if needed.
"""

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from src.utils import (
    DATA_PROC,
    CRS_GEO,
    find_col,
    get_logger,
    normalize_ubigeo,
)

log = get_logger("cleaning")

# ── IPRESS ────────────────────────────────────────────────────────────────────

IPRESS_COL_MAP = {
    "codigo":     ["Código Único", "codigo_renaes", "cod_renaes", "codigo", "renaes", "id_ipress"],
    "nombre":     ["Nombre del establecimiento", "nombre", "nombre_ipress", "razon_social"],
    "categoria":  ["Categoria", "Clasificación", "categoria", "categoria_establecimiento", "nivel"],
    "ubigeo":     ["UBIGEO", "ubigeo", "cod_ubigeo", "ubigeo_inei"],
    "distrito":   ["Distrito", "distrito", "nom_dis"],
    "provincia":  ["Provincia", "provincia", "nom_prov"],
    "departamento": ["Departamento", "departamento", "nom_dep", "dpto"],
    # NOTE: In the MINSA IPRESS dataset the column named NORTE holds longitude
    # and ESTE holds latitude (the values confirm this: NORTE ≈ -69 to -81 lon,
    # ESTE ≈ -0 to -18 lat). We remap them accordingly.
    "latitud":    ["ESTE", "latitud", "lat", "latitude"],
    "longitud":   ["NORTE", "longitud", "lon", "longitude"],
    "estado":     ["Estado", "estado", "estado_ipress", "activo"],
}


def clean_ipress(df_raw: pd.DataFrame) -> pd.DataFrame:
    log.info("Cleaning IPRESS (%d rows)...", len(df_raw))
    df = df_raw.copy()
    df.columns = df.columns.str.strip()

    renamed = {}
    for std_name, candidates in IPRESS_COL_MAP.items():
        col = find_col(df, candidates, required=(std_name in ("latitud", "longitud", "ubigeo")))
        if col:
            renamed[col] = std_name
    df.rename(columns=renamed, inplace=True)

    # Numeric coordinates
    df["latitud"]  = pd.to_numeric(df["latitud"],  errors="coerce")
    df["longitud"] = pd.to_numeric(df["longitud"], errors="coerce")

    before = len(df)
    df = df.dropna(subset=["latitud", "longitud"])
    # Peru bounding box roughly: lat -18.4 to -0.03, lon -81.3 to -68.7
    df = df[
        df["latitud"].between(-20.0, 1.0) &
        df["longitud"].between(-82.0, -68.0)
    ]
    log.info("  Removed %d rows with invalid/missing coordinates.", before - len(df))

    # Active facilities only
    if "estado" in df.columns:
        mask_active = df["estado"].astype(str).str.upper().isin(
            ["ACTIVO", "ACTIVADO", "1", "TRUE", "SI", "OPERATIVO", "HABILITADO"]
        )
        before = len(df)
        df = df[mask_active | df["estado"].isna()]
        log.info("  Removed %d inactive facilities.", before - len(df))

    # Normalize ubigeo
    if "ubigeo" in df.columns:
        df["ubigeo"] = normalize_ubigeo(df["ubigeo"])

    df.drop_duplicates(inplace=True)
    log.info("  Final IPRESS rows: %d", len(df))

    out = DATA_PROC / "ipress_clean.csv"
    df.to_csv(out, index=False)
    log.info("  Saved → %s", out)
    return df


# ── Centros Poblados ──────────────────────────────────────────────────────────

CP_COL_MAP = {
    # IGN shapefile column names
    "nombre":     ["NOM_POBLAD", "nombre", "nombcp", "centro_poblado"],
    "tipo":       ["CAT_POBLAD", "CATEGORIA", "tipo", "tipo_cp"],
    "distrito":   ["DIST", "distrito", "nom_dis"],
    "provincia":  ["PROV", "provincia", "nom_prov"],
    "departamento": ["DEP", "departamento", "nom_dep"],
    # X = longitude, Y = latitude in the IGN shapefile
    "longitud":   ["X", "longitud", "lon", "longitude"],
    "latitud":    ["Y", "latitud", "lat", "latitude"],
}


def clean_centros_poblados(df_raw) -> gpd.GeoDataFrame:
    """Accept either a GeoDataFrame (shapefile) or a plain DataFrame."""
    log.info("Cleaning Centros Poblados (%d rows)...", len(df_raw))

    # Normalise to GeoDataFrame
    if isinstance(df_raw, gpd.GeoDataFrame):
        gdf = df_raw.copy()
    else:
        df = df_raw.copy()
        df.columns = df.columns.str.strip()
        renamed = {}
        for std_name, candidates in CP_COL_MAP.items():
            col = find_col(df, candidates, required=(std_name in ("latitud", "longitud")))
            if col:
                renamed[col] = std_name
        df.rename(columns=renamed, inplace=True)
        df["latitud"]  = pd.to_numeric(df["latitud"],  errors="coerce")
        df["longitud"] = pd.to_numeric(df["longitud"], errors="coerce")
        df = df.dropna(subset=["latitud", "longitud"])
        geometry = gpd.points_from_xy(df["longitud"], df["latitud"])
        gdf = gpd.GeoDataFrame(df, geometry=geometry, crs=CRS_GEO)

    # Rename columns using CP_COL_MAP
    renamed = {}
    for std_name, candidates in CP_COL_MAP.items():
        col = find_col(gdf, candidates, required=False)
        if col and col not in renamed:
            renamed[col] = std_name
    gdf.rename(columns=renamed, inplace=True)

    # Ensure CRS = WGS84
    if gdf.crs is None:
        gdf = gdf.set_crs(CRS_GEO)
    else:
        gdf = gdf.to_crs(CRS_GEO)

    # Coordinate filter using geometry bounds
    before = len(gdf)
    bounds = gdf.geometry.bounds
    valid = (
        bounds["miny"].between(-20.0, 1.0) &
        bounds["minx"].between(-82.0, -68.0)
    )
    gdf = gdf[valid]
    log.info("  Removed %d CP rows with invalid coords.", before - len(gdf))

    # Derive latitud/longitud columns from geometry for downstream use
    gdf["latitud"]  = gdf.geometry.y
    gdf["longitud"] = gdf.geometry.x

    # Deduplicate by name + approximate location
    if "nombre" in gdf.columns:
        before = len(gdf)
        gdf = gdf.drop_duplicates(subset=["nombre", "latitud", "longitud"])
        log.info("  Removed %d duplicate CP rows.", before - len(gdf))

    log.info("  Final CP rows: %d", len(gdf))
    out = DATA_PROC / "centros_poblados_clean.geojson"
    gdf.to_file(out, driver="GeoJSON")
    log.info("  Saved → %s", out)
    return gdf


# ── Emergencias ───────────────────────────────────────────────────────────────

EMERG_COL_MAP = {
    "codigo":     ["CO_IPRESS", "codigo_renaes", "cod_renaes", "codigo_ipress"],
    "nombre":     ["RAZON_SOC", "nombre_ipress", "nombre", "razon_social"],
    "ubigeo":     ["UBIGEO", "ubigeo", "cod_ubigeo"],
    "distrito":   ["DISTRITO", "distrito", "nom_dis"],
    "departamento": ["DEPARTAMENTO", "departamento", "nom_dep"],
    "anio":       ["ANHO", "anio", "año", "year"],
    "mes":        ["MES", "mes", "month"],
    "total":      [
        "NRO_TOTAL_ATENCIONES", "NRO_TOTAL_ATENDIDOS",
        "total", "em_total", "total_emergencias", "n_emergencias",
    ],
}


def clean_emergencias(df_raw: pd.DataFrame, df_ipress_clean: pd.DataFrame | None = None) -> pd.DataFrame:
    log.info("Cleaning Emergencias (%d rows)...", len(df_raw))
    df = df_raw.copy()
    df.columns = df.columns.str.strip()

    renamed = {}
    for std_name, candidates in EMERG_COL_MAP.items():
        col = find_col(df, candidates, required=False)
        if col:
            renamed[col] = std_name
    df.rename(columns=renamed, inplace=True)

    # If "total" column not found, sum numeric columns that look like emergency counts
    if "total" not in df.columns:
        num_cols = df.select_dtypes(include="number").columns.tolist()
        id_like  = {"anio", "mes", "codigo", "ubigeo"} & set(df.columns)
        sum_cols = [c for c in num_cols if c not in id_like]
        if sum_cols:
            df["total"] = df[sum_cols].sum(axis=1)
            log.info("  Derived 'total' by summing: %s", sum_cols)

    df["total"] = pd.to_numeric(df.get("total", pd.Series(0, index=df.index)), errors="coerce").fillna(0)

    # Normalize codes
    if "codigo" in df.columns:
        df["codigo"] = df["codigo"].astype(str).str.strip().str.upper()

    if "ubigeo" not in df.columns and df_ipress_clean is not None and "codigo" in df.columns:
        ip = df_ipress_clean[["codigo", "ubigeo"]].drop_duplicates()
        ip["codigo"] = ip["codigo"].astype(str).str.strip().str.upper()
        df = df.merge(ip, on="codigo", how="left")
        log.info("  Joined ubigeo from IPRESS clean table.")

    if "ubigeo" in df.columns:
        df["ubigeo"] = normalize_ubigeo(df["ubigeo"])

    # Aggregate to ubigeo (district) level
    agg_cols = {"total": "sum"}
    if "anio" in df.columns:
        agg_cols_extra = {}
        group_keys = ["ubigeo"] if "ubigeo" in df.columns else []
        if not group_keys:
            log.warning("  No ubigeo column — cannot aggregate by district.")
        else:
            df_agg = df.groupby(group_keys, as_index=False)["total"].sum()
            df_agg.rename(columns={"total": "total_emergencias"}, inplace=True)
    else:
        if "ubigeo" in df.columns:
            df_agg = df.groupby("ubigeo", as_index=False)["total"].sum()
            df_agg.rename(columns={"total": "total_emergencias"}, inplace=True)
        else:
            df_agg = df.copy()
            df_agg["total_emergencias"] = df_agg["total"]

    log.info("  Aggregated to %d district rows.", len(df_agg))
    out = DATA_PROC / "emergencias_clean.csv"
    df_agg.to_csv(out, index=False)
    log.info("  Saved → %s", out)
    return df_agg


# ── Distritos ─────────────────────────────────────────────────────────────────

DIST_COL_MAP = {
    "ubigeo":       ["IDDIST", "ubigeo", "cod_ubigeo", "ubigeo_inei", "codgeo"],
    "distrito":     ["DISTRITO", "distrito", "nom_dis", "nombdist"],
    "provincia":    ["PROVINCIA", "provincia", "nom_prov", "nombprov"],
    "departamento": ["DEPARTAMEN", "departamento", "nom_dep", "nombdep"],
    "poblacion":    ["poblacion", "pob_total", "pob2017", "pob"],
}


def clean_distritos(gdf_raw: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    log.info("Cleaning Distritos (%d rows)...", len(gdf_raw))
    gdf = gdf_raw.copy()
    gdf.columns = gdf.columns.str.strip()

    renamed = {}
    for std_name, candidates in DIST_COL_MAP.items():
        col = find_col(gdf, candidates, required=False)
        if col:
            renamed[col] = std_name
    gdf.rename(columns=renamed, inplace=True)

    if "ubigeo" in gdf.columns:
        gdf["ubigeo"] = normalize_ubigeo(gdf["ubigeo"])

    # Ensure geographic CRS
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    else:
        gdf = gdf.to_crs("EPSG:4326")

    # Repair invalid geometries
    invalid = (~gdf.geometry.is_valid).sum()
    if invalid > 0:
        log.info("  Repairing %d invalid geometries.", invalid)
        gdf["geometry"] = gdf.geometry.buffer(0)

    log.info("  Final Distritos rows: %d", len(gdf))
    out = DATA_PROC / "distritos_clean.geojson"
    gdf.to_file(out, driver="GeoJSON")
    log.info("  Saved → %s", out)
    return gdf


# ── Run all ───────────────────────────────────────────────────────────────────

def clean_all(raw: dict) -> dict:
    """
    Parameters
    ----------
    raw : dict with keys 'ipress', 'centros_poblados', 'emergencias', 'distritos'

    Returns
    -------
    dict with cleaned DataFrames/GeoDataFrames
    """
    ipress_clean = clean_ipress(raw["ipress"])
    cp_clean     = clean_centros_poblados(raw["centros_poblados"])
    emerg_clean  = clean_emergencias(raw["emergencias"], ipress_clean)
    dist_clean   = clean_distritos(raw["distritos"])

    return {
        "ipress":           ipress_clean,
        "centros_poblados": cp_clean,
        "emergencias":      emerg_clean,
        "distritos":        dist_clean,
    }
