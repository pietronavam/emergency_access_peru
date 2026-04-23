# Emergency Healthcare Access Inequality in Peru

A district-level geospatial analytics pipeline to study emergency healthcare
access inequality across Peru's 1 874 districts.

---

## What does this project do?

It integrates four public datasets — health facilities (IPRESS), populated
centres, emergency production statistics (SUSALUD C1), and district boundaries
— to build a composite **Emergency Healthcare Access Index (EHAI)** for every
district in Peru.  The index is visualised through a Streamlit application
with static charts, choropleth maps, and interactive Folium layers.

---

## Main analytical goal

Answer which districts appear *relatively better or worse served* in emergency
healthcare access, and quantify how sensitive that conclusion is to different
methodological definitions of "access".

---

## Datasets used

| Dataset | Source |
|---|---|
| IPRESS health facilities | MINSA via [datosabiertos.gob.pe](https://www.datosabiertos.gob.pe/dataset/minsa-ipress) |
| Centros Poblados | INEI via [datosabiertos.gob.pe](https://www.datosabiertos.gob.pe/dataset/dataset-centros-poblados) |
| Emergency production C1 | [datos.susalud.gob.pe](http://datos.susalud.gob.pe/dataset/consulta-c1-produccion-asistencial-en-emergencia-por-ipress) |
| District boundaries (shapefile) | [d2cml-ai GitHub repo](https://github.com/d2cml-ai/Data-Science-Python/blob/main/_data/Folium/DISTRITOS.shp) |

---

## How were the data cleaned?

See `src/cleaning.py` for full implementation.  Key decisions:

- **IPRESS**: removed facilities with missing or out-of-Peru coordinates;
  retained only active facilities; standardised UBIGEO to 6-char zero-padded
  strings.
- **Centros Poblados**: same coordinate filter; de-duplicated by (ubigeo,
  name).
- **Emergencias**: aggregated monthly records to district-level annual totals;
  recovered missing UBIGEO by joining with IPRESS clean table.
- **Distritos**: repaired invalid geometries with `buffer(0)`; normalised CRS
  to EPSG:4326.

---

## How were the district-level metrics constructed?

The **EHAI** has three components, each min-max normalised to [0, 1]:

| Component | Definition |
|---|---|
| A — Facility density | Facilities per 10 000 population (or per km² if population unavailable) |
| B — Emergency activity | Emergency consultations per 1 000 population |
| C — Spatial access | % of populated centres within threshold distance of nearest IPRESS |

**Baseline**: equal weights (⅓ each), distance threshold = 5 km, any IPRESS.

**Alternative**: weights A=0.20, B=0.20, C=0.60; threshold = 10 km;
high-capacity IPRESS (level II+) only.

CRS for distance calculations: **EPSG:32718** (UTM Zone 18S), re-projected to
EPSG:4326 for storage and visualisation.

---

## How to install the dependencies?

```bash
pip install -r requirements.txt
```

Requires Python ≥ 3.10.

---

## How to run the processing pipeline?

```bash
# Download data and run the full pipeline
python run_pipeline.py

# If you have already downloaded the data manually into data/raw/
python run_pipeline.py --skip-download
```

Manual download instructions (if automatic download fails):

1. **IPRESS** → download CSV from https://www.datosabiertos.gob.pe/dataset/minsa-ipress → save as `data/raw/ipress.csv`
2. **Centros Poblados** → download CSV from https://www.datosabiertos.gob.pe/dataset/dataset-centros-poblados → save as `data/raw/centros_poblados.csv`
3. **Emergencias** → download CSV from http://datos.susalud.gob.pe/dataset/consulta-c1-produccion-asistencial-en-emergencia-por-ipress → save as `data/raw/emergencias.csv`
4. **Distritos** → download `.shp`, `.shx`, `.dbf`, `.prj` from https://github.com/d2cml-ai/Data-Science-Python/tree/main/_data/Folium → save into `data/raw/`

---

## How to run the Streamlit app?

```bash
streamlit run app.py
```

---

## Main findings

> *Run the pipeline to populate this section with actual results.*

Preliminary analytical expectations based on literature:

- Districts in **Amazonia** (Loreto, Ucayali) and **southern highland** regions
  (Puno, Apurímac) are expected to score lowest on spatial access due to
  geographic isolation and low facility density.
- **Lima Metropolitana** districts should score highest on all three
  components.
- The **alternative specification** (weighting spatial access 60%) is expected
  to widen the gap between rural and urban districts relative to the baseline,
  as rural districts are most penalised by proximity-based definitions.

---

## Main limitations

- **Straight-line distance** is used instead of road-network travel time.
  Andean terrain makes real access worse than Euclidean distance implies.
- **Population data** may be outdated (last census 2017); districts with
  significant post-census migration will have incorrect density estimates.
- **Private facilities** not registered in MINSA IPRESS are excluded, causing
  underestimation of access in wealthier districts.
- **Temporal mismatch**: facility data and emergency production data may
  correspond to different years.

---

## Repository structure

```
emergency_access_peru/
├── app.py                    # Streamlit app (4 tabs)
├── run_pipeline.py           # End-to-end pipeline runner
├── README.md
├── requirements.txt
├── src/
│   ├── data_loader.py        # Download + load raw datasets
│   ├── cleaning.py           # Standardise + validate
│   ├── geospatial.py         # Spatial joins, distances, GeoDataFrames
│   ├── metrics.py            # EHAI index (baseline + alternative)
│   ├── visualization.py      # Static charts and Folium maps
│   └── utils.py              # Constants, helpers, CRS definitions
├── data/
│   ├── raw/                  # Original downloaded files
│   └── processed/            # Cleaned outputs (CSV, GeoJSON)
├── output/
│   ├── figures/              # PNG charts and maps
│   └── tables/               # District metrics CSV, sensitivity comparison
└── video/
    └── link.txt              # Link to explanatory video
```
