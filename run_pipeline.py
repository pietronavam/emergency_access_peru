"""
run_pipeline.py — Execute the full data pipeline end-to-end.

Steps
-----
1. Download raw data (if not already present)
2. Load raw data
3. Clean all datasets
4. Build geospatial pipeline (spatial joins + distances)
5. Compute district-level metrics (EHAI)
6. Generate all visualisations

Usage
-----
    python run_pipeline.py

Options
-------
    --skip-download   Skip downloading data (use existing files in data/raw/)
    --force-download  Re-download all files even if they already exist
"""

import argparse
import sys
import traceback

from src.utils import get_logger

log = get_logger("pipeline")


def main(args):
    # ── Step 1: Download ──────────────────────────────────────────────────────
    if not args.skip_download:
        log.info("=== Step 1: Downloading raw data ===")
        from src.data_loader import (
            download_ipress,
            download_centros_poblados,
            download_emergencias,
            download_distritos,
        )
        force = args.force_download
        errors = []
        for fn, name in [
            (download_distritos,        "District shapefile"),
            (download_ipress,           "IPRESS"),
            (download_centros_poblados, "Centros Poblados"),
            (download_emergencias,      "Emergencias"),
        ]:
            try:
                fn(force=force)
            except Exception as e:
                log.error("Could not download %s: %s", name, e)
                errors.append(name)
        if errors:
            log.warning(
                "\nCould not auto-download: %s\n"
                "Place the files manually in data/raw/ and re-run with --skip-download.",
                ", ".join(errors),
            )
    else:
        log.info("=== Step 1: Skipped (--skip-download) ===")

    # ── Step 2: Load raw ──────────────────────────────────────────────────────
    log.info("=== Step 2: Loading raw data ===")
    from src.data_loader import load_all_raw
    raw = load_all_raw()

    # ── Step 3: Clean ─────────────────────────────────────────────────────────
    log.info("=== Step 3: Cleaning datasets ===")
    from src.cleaning import clean_all
    cleaned = clean_all(raw)

    # ── Step 4: Geospatial pipeline ───────────────────────────────────────────
    log.info("=== Step 4: Building geospatial pipeline ===")
    from src.geospatial import build_geospatial_pipeline
    gdf_access = build_geospatial_pipeline(cleaned)

    # ── Step 5: Metrics ───────────────────────────────────────────────────────
    log.info("=== Step 5: Computing district metrics ===")
    from src.metrics import compute_all_metrics
    gdf_metrics = compute_all_metrics(gdf_access)

    # ── Step 6: Visualisations ────────────────────────────────────────────────
    log.info("=== Step 6: Generating visualisations ===")
    from src.geospatial import build_gdf_ipress
    from src.visualization import generate_all_visuals
    gdf_ipress = build_gdf_ipress(cleaned["ipress"])
    generate_all_visuals(gdf_metrics, gdf_ipress)

    log.info("=== Pipeline complete! ===")
    log.info("Run the app with:  streamlit run app.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Emergency Access Peru pipeline.")
    parser.add_argument("--skip-download",   action="store_true", help="Skip data download step.")
    parser.add_argument("--force-download",  action="store_true", help="Re-download even if files exist.")
    args = parser.parse_args()

    try:
        main(args)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
