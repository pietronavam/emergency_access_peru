# Data Dictionary

## Raw datasets

### ipress.csv — MINSA Health Facilities
| Column | Description |
|---|---|
| Código Único | Unique IPRESS identifier (RENAES code) |
| Nombre del establecimiento | Facility name |
| Categoria | MINSA category (I-1 to III-E) |
| UBIGEO | 6-digit district code |
| Departamento / Provincia / Distrito | Administrative location |
| NORTE | Longitude in decimal degrees (column name is misleading in source) |
| ESTE | Latitude in decimal degrees (column name is misleading in source) |
| Estado | Operational status (ACTIVADO = active) |

### CCPP_IGN100K.shp — Populated Centres (IGN)
| Column | Description |
|---|---|
| NOM_POBLAD | Name of populated centre |
| CAT_POBLAD | Category (city, town, village, etc.) |
| DEP / PROV / DIST | Department / Province / District names |
| X | Longitude (decimal degrees, WGS-84) |
| Y | Latitude (decimal degrees, WGS-84) |

### emergencias.csv — SUSALUD C1 Emergency Production (2022–2024)
| Column | Description |
|---|---|
| ANHO | Year |
| MES | Month (1–12) |
| UBIGEO | 6-digit district code |
| CO_IPRESS | Facility identifier |
| RAZON_SOC | Facility name |
| NRO_TOTAL_ATENCIONES | Total emergency consultations (NE_ prefix = not specified → treated as 0) |
| CATEGORIA | Facility category |

### DISTRITOS.shp — District Boundaries
| Column | Description |
|---|---|
| IDDIST | 6-digit district UBIGEO code |
| DISTRITO | District name |
| PROVINCIA | Province name |
| DEPARTAMEN | Department name |
| geometry | Polygon boundary (WGS-84 / EPSG:4326) |

---

## Processed datasets (data/processed/)

### ipress_clean.csv
Cleaned IPRESS with standardised column names: `codigo`, `nombre`, `categoria`, `ubigeo`, `latitud`, `longitud`, `estado`.  
Filtering: removed rows with missing/invalid coordinates and inactive facilities. **7,952 rows**.

### centros_poblados_clean.geojson
Cleaned populated centres GeoDataFrame.  
Filtering: bounding-box coordinate filter, de-duplicated by name+location. **136,543 rows**.

### emergencias_clean.csv
Aggregated to district level (ubigeo). Columns: `ubigeo`, `total_emergencias`. **1,030 rows** (districts with at least one recorded emergency).

### distritos_clean.geojson
District polygons with standardised column names. Invalid geometries repaired. **1,873 rows**.

### district_metrics.geojson / district_metrics.csv (output/tables/)
One row per district with all analytical variables:

| Column | Description |
|---|---|
| ubigeo | 6-digit district code |
| distrito / departamento / provincia | Administrative labels |
| n_facilities | Number of IPRESS in district |
| n_hicat_facilities | Number of level II+ IPRESS |
| n_centros_poblados | Number of populated centres in district |
| pct_cp_within_5km | % of populated centres within 5 km of any IPRESS (baseline) |
| pct_cp_within_10km | % within 10 km (alternative) |
| pct_cp_hicat_within_5km | % within 5 km of level II+ IPRESS |
| pct_cp_hicat_within_10km | % within 10 km of level II+ IPRESS |
| total_emergencias | Total emergency consultations 2022–2024 |
| comp_facility_base | Normalised facility density component (baseline) |
| comp_emergency_base | Normalised emergency activity component (baseline) |
| comp_access_base | Normalised spatial access component (baseline) |
| ehai_base | Composite EHAI score — baseline (0=worst, 1=best) |
| category_base | Quartile category (Underserved / Moderate-Low / Moderate-High / Well-served) |
| ehai_alt | Composite EHAI score — alternative specification |
| category_alt | Quartile category — alternative specification |

---

## Filtering and cleaning decisions summary

| Decision | Rationale |
|---|---|
| Remove IPRESS with missing coordinates | Cannot be placed on map; ~61% of records lack coords in source |
| Treat NORTE as longitude, ESTE as latitude | Value ranges confirm this swap exists in the MINSA source file |
| Keep only ACTIVADO facilities | Inactive/closed facilities do not provide emergency care |
| Normalise UBIGEO to 6-char zero-padded string | Ensures consistent join keys across all datasets |
| Aggregate emergencias by district | Monthly × facility granularity not needed for district comparison |
| Treat NE_* values in emergencias as 0 | "No Especificado" means the data was not reported, not that zero care was given |
| Repair shapefile geometries with buffer(0) | Prevents spatial join errors from self-intersecting polygons |
| Use EPSG:32718 for distance calculation | UTM Zone 18S minimises metric distortion for mainland Peru |
