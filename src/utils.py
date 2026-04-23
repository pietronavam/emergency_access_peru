"""
utils.py — Shared constants, paths, and helper functions.
"""

import logging
import os
from pathlib import Path

# ── Coordinate Reference Systems ──────────────────────────────────────────────
CRS_GEO  = "EPSG:4326"   # WGS-84 geographic (lat/lon) — storage & Folium
CRS_PROJ = "EPSG:32718"  # UTM Zone 18S — metric CRS for Peru distance calcs

# ── Distance thresholds (metres) ──────────────────────────────────────────────
DISTANCE_BASELINE_M = 5_000   # 5 km  — baseline access definition
DISTANCE_ALT_M      = 10_000  # 10 km — alternative access definition

# ── Composite score weights ────────────────────────────────────────────────────
WEIGHTS_BASELINE = {"facilities": 1/3, "emergency": 1/3, "access": 1/3}
WEIGHTS_ALT      = {"facilities": 0.20, "emergency": 0.20, "access": 0.60}

# ── High-category facility codes (MINSA classification) ───────────────────────
# Levels III and IV are the ones with full emergency capability
EMERGENCY_CATEGORIES = {
    "I-1", "I-2", "I-3", "I-4",
    "II-1", "II-2", "II-E",
    "III-1", "III-2", "III-E",
}
HIGH_CAPACITY_CATEGORIES = {"II-1", "II-2", "II-E", "III-1", "III-2", "III-E"}

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT         = Path(__file__).resolve().parent.parent
DATA_RAW     = ROOT / "data" / "raw"
DATA_PROC    = ROOT / "data" / "processed"
OUTPUT_FIGS  = ROOT / "output" / "figures"
OUTPUT_TABS  = ROOT / "output" / "tables"

for _p in [DATA_RAW, DATA_PROC, OUTPUT_FIGS, OUTPUT_TABS]:
    _p.mkdir(parents=True, exist_ok=True)

# ── Logging ───────────────────────────────────────────────────────────────────
def get_logger(name: str) -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(name)s | %(levelname)s | %(message)s",
    )
    return logging.getLogger(name)


# ── Column-name resolver ───────────────────────────────────────────────────────
def find_col(df, candidates: list[str], required: bool = True) -> str | None:
    """Return the first column in *candidates* that exists in df (case-insensitive)."""
    cols_lower = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in cols_lower:
            return cols_lower[cand.lower()]
    if required:
        raise KeyError(
            f"None of the expected columns {candidates} found in DataFrame.\n"
            f"Available columns: {list(df.columns)}"
        )
    return None


def normalize_ubigeo(series):
    """Zero-pad ubigeo codes to 6 characters."""
    return series.astype(str).str.strip().str.zfill(6)
