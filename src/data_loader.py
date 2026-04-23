"""
data_loader.py — Download and load raw datasets from public portals.

Datasets
--------
1. IPRESS (health facilities)       — datosabiertos.gob.pe / MINSA
2. Centros Poblados                 — datosabiertos.gob.pe / INEI
3. Emergency production (C1 SUSALUD)— datos.susalud.gob.pe
4. District boundaries (shapefile)  — GitHub d2cml-ai repo
"""

import io
import os
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

from src.utils import DATA_RAW, get_logger

log = get_logger("data_loader")

# ── CKAN portal helpers ────────────────────────────────────────────────────────

def _ckan_resource_urls(portal: str, package_id: str) -> list[dict]:
    """Return list of resource dicts from a CKAN package."""
    url = f"{portal}/api/3/action/package_show?id={package_id}"
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        return r.json()["result"]["resources"]
    except Exception as exc:
        log.warning("CKAN API call failed (%s): %s", url, exc)
        return []


def _best_resource(resources: list[dict], preferred_formats=("CSV", "XLSX", "XLS")) -> dict | None:
    """Pick the best downloadable resource by format preference."""
    for fmt in preferred_formats:
        for res in resources:
            if res.get("format", "").upper() == fmt:
                return res
    return resources[0] if resources else None


def _download(url: str, dest: Path, chunk_size: int = 1 << 20) -> Path:
    """Stream-download *url* to *dest*. Returns dest."""
    log.info("Downloading %s → %s", url, dest.name)
    r = requests.get(url, timeout=120, stream=True)
    r.raise_for_status()
    with open(dest, "wb") as fh:
        for chunk in r.iter_content(chunk_size=chunk_size):
            fh.write(chunk)
    log.info("Saved %s (%.1f MB)", dest.name, dest.stat().st_size / 1e6)
    return dest


# ── 1. IPRESS ─────────────────────────────────────────────────────────────────

IPRESS_PORTAL  = "https://www.datosabiertos.gob.pe"
IPRESS_PACKAGE = "minsa-ipress"
IPRESS_FILE    = DATA_RAW / "ipress.csv"


def download_ipress(force: bool = False) -> Path:
    if IPRESS_FILE.exists() and not force:
        log.info("IPRESS file already present: %s", IPRESS_FILE)
        return IPRESS_FILE
    resources = _ckan_resource_urls(IPRESS_PORTAL, IPRESS_PACKAGE)
    res = _best_resource(resources, ("CSV", "XLSX", "XLS"))
    if res is None:
        _manual_instruction(
            "IPRESS",
            "https://www.datosabiertos.gob.pe/dataset/minsa-ipress",
            IPRESS_FILE,
        )
        raise FileNotFoundError(f"Could not auto-download IPRESS. Place file at {IPRESS_FILE}")
    ext = res.get("format", "CSV").lower()
    dest = DATA_RAW / f"ipress.{ext}"
    _download(res["url"], dest)
    if dest != IPRESS_FILE:
        dest.rename(IPRESS_FILE)
    return IPRESS_FILE


def load_ipress() -> pd.DataFrame:
    _ensure_file(IPRESS_FILE, download_ipress)
    df = _read_tabular(IPRESS_FILE)
    log.info("IPRESS loaded: %d rows, %d cols", *df.shape)
    return df


# ── 2. Centros Poblados ───────────────────────────────────────────────────────

CP_PORTAL  = "https://www.datosabiertos.gob.pe"
CP_PACKAGE = "dataset-centros-poblados"
CP_FILE    = DATA_RAW / "centros_poblados.csv"


def download_centros_poblados(force: bool = False) -> Path:
    if CP_FILE.exists() and not force:
        log.info("Centros Poblados file already present: %s", CP_FILE)
        return CP_FILE
    resources = _ckan_resource_urls(CP_PORTAL, CP_PACKAGE)
    res = _best_resource(resources, ("CSV", "XLSX", "XLS"))
    if res is None:
        _manual_instruction(
            "Centros Poblados",
            "https://www.datosabiertos.gob.pe/dataset/dataset-centros-poblados",
            CP_FILE,
        )
        raise FileNotFoundError(f"Could not auto-download Centros Poblados. Place file at {CP_FILE}")
    ext = res.get("format", "CSV").lower()
    dest = DATA_RAW / f"centros_poblados.{ext}"
    _download(res["url"], dest)
    if dest != CP_FILE:
        dest.rename(CP_FILE)
    return CP_FILE


def load_centros_poblados() -> pd.DataFrame:
    _ensure_file(CP_FILE, download_centros_poblados)
    df = _read_tabular(CP_FILE)
    log.info("Centros Poblados loaded: %d rows, %d cols", *df.shape)
    return df


# ── 3. Emergency production (SUSALUD C1) ─────────────────────────────────────

SUSALUD_PORTAL  = "https://datos.susalud.gob.pe"
SUSALUD_PACKAGE = "consulta-c1-produccion-asistencial-en-emergencia-por-ipress"
EMERG_FILE      = DATA_RAW / "emergencias.csv"


def download_emergencias(force: bool = False) -> Path:
    if EMERG_FILE.exists() and not force:
        log.info("Emergency file already present: %s", EMERG_FILE)
        return EMERG_FILE
    resources = _ckan_resource_urls(SUSALUD_PORTAL, SUSALUD_PACKAGE)
    res = _best_resource(resources, ("CSV", "XLSX", "XLS"))
    if res is None:
        _manual_instruction(
            "Emergencias SUSALUD",
            "http://datos.susalud.gob.pe/dataset/consulta-c1-produccion-asistencial-en-emergencia-por-ipress",
            EMERG_FILE,
        )
        raise FileNotFoundError(f"Could not auto-download emergencias. Place file at {EMERG_FILE}")
    ext = res.get("format", "CSV").lower()
    dest = DATA_RAW / f"emergencias.{ext}"
    _download(res["url"], dest)
    if dest != EMERG_FILE:
        dest.rename(EMERG_FILE)
    return EMERG_FILE


def load_emergencias() -> pd.DataFrame:
    _ensure_file(EMERG_FILE, download_emergencias)
    df = _read_tabular(EMERG_FILE)
    log.info("Emergencias loaded: %d rows, %d cols", *df.shape)
    return df


# ── 4. District boundaries (shapefile from GitHub) ───────────────────────────

DISTRITOS_BASE = (
    "https://github.com/d2cml-ai/Data-Science-Python/raw/main/_data/Folium/"
)
SHP_EXTS  = ["shp", "shx", "dbf", "prj", "cpg"]
SHP_FILE  = DATA_RAW / "DISTRITOS.shp"


def download_distritos(force: bool = False) -> Path:
    if SHP_FILE.exists() and not force:
        log.info("Shapefile already present: %s", SHP_FILE)
        return SHP_FILE
    for ext in SHP_EXTS:
        fname = f"DISTRITOS.{ext}"
        dest  = DATA_RAW / fname
        if dest.exists() and not force:
            continue
        try:
            _download(DISTRITOS_BASE + fname, dest)
        except Exception as exc:
            log.warning("Could not download %s: %s", fname, exc)
    if not SHP_FILE.exists():
        _manual_instruction(
            "DISTRITOS shapefile",
            "https://github.com/d2cml-ai/Data-Science-Python/tree/main/_data/Folium",
            DATA_RAW / "DISTRITOS.shp",
        )
        raise FileNotFoundError(f"Shapefile not found at {SHP_FILE}")
    return SHP_FILE


def load_distritos() -> gpd.GeoDataFrame:
    _ensure_file(SHP_FILE, download_distritos)
    gdf = gpd.read_file(SHP_FILE)
    log.info("Distritos loaded: %d rows, %d cols", *gdf.shape)
    return gdf


# ── Helpers ───────────────────────────────────────────────────────────────────

def _read_tabular(path: Path, **kwargs) -> pd.DataFrame:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        return pd.read_excel(path, **kwargs)
    encodings = ["utf-8", "latin-1", "cp1252"]
    separators = [",", ";", "|", "\t"]
    last_err = None
    for enc in encodings:
        for sep in separators:
            try:
                df = pd.read_csv(path, encoding=enc, sep=sep, low_memory=False, **kwargs)
                if df.shape[1] > 1:
                    return df
            except Exception as e:
                last_err = e
    raise ValueError(f"Could not read {path}. Last error: {last_err}")


def _ensure_file(path: Path, downloader):
    if not Path(path).exists():
        log.info("File not found locally — attempting download.")
        downloader()


def _manual_instruction(name: str, url: str, dest: Path):
    log.error(
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "  MANUAL DOWNLOAD REQUIRED: %s\n"
        "  URL : %s\n"
        "  Save to: %s\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        name, url, dest,
    )


# ── Convenience: load all ─────────────────────────────────────────────────────

def load_all_raw() -> dict:
    """Load all four raw datasets and return as a dict."""
    return {
        "ipress":           load_ipress(),
        "centros_poblados": load_centros_poblados(),
        "emergencias":      load_emergencias(),
        "distritos":        load_distritos(),
    }
