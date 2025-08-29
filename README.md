# osm-3d-stat

**English** | [日本語](README_JP.md)

A comprehensive pipeline for extracting and analyzing 3D building attributes (height, floors, etc.) from OpenStreetMap (OSM) data.

## 📋 Overview

This project provides a complete toolset for analyzing 3D information distribution patterns, geographical disparities in editing activities, and data quality assessment of building data in OpenStreetMap. It is designed to support academic research and urban planning applications utilizing OSM data.

## ✨ Key Features

- **Automated OSM Data Extraction**: Efficiently extract building data from OSM PBF files
- **3D Attribute Analysis**: Statistical analysis of building heights, floors, underground levels, etc.
- **Geographic Distribution Visualization**: Coverage analysis by prefecture and municipality
- **Editor Activity Analysis**: Contribution pattern analysis using concentration indices (Gini coefficient, HHI)
- **Multi-format Data Export**: Output results in CSV, GeoPackage, and GeoParquet formats

## 🛠 Requirements

### Software Dependencies
- PostgreSQL 13+ (with PostGIS extension)
- Python 3.7+
- osm2pgsql
- GDAL/OGR 3.5+ (for GeoParquet export)

### Python Packages
```bash
pip install geopandas sqlalchemy psycopg2-binary pyogrio
```

## 📦 Installation

1. Clone the repository
```bash
git clone https://github.com/your-username/osm-3d-stat.git
cd osm-3d-stat
```

2. Make scripts executable
```bash
chmod +x import_osm_buildings.sh export_buildings.sh
```

## 🚀 Usage

### 1. Data Import

```bash
# Basic usage
./import_osm_buildings.sh [database_name] [username] [admin_boundaries_shapefile] [osm_pbf_file]

# Example
./import_osm_buildings.sh osm_3ddata_analysis postgres N03-23_230101.shp japan-250201-internal.osm.pbf

# Limit processing count
./import_osm_buildings.sh osm_3ddata_analysis postgres N03-23_230101.shp japan-250201-internal.osm.pbf 10000
```

### 2. Run Analysis

```bash
python building_analysis.py --dbname osm_3ddata_analysis --user postgres --debug
```

### 3. Data Export

```bash
# GeoPackage format (default)
./export_buildings.sh

# Specific format output
./export_buildings.sh osm_3ddata_analysis postgres fgb buildings.fgb

# With filter conditions
./export_buildings.sh osm_3ddata_analysis postgres gpkg tall_buildings.gpkg "height > 50"
```

## 📊 Database Structure

### Main Tables
- **admin_boundaries**: Administrative boundary data
- **building_history**: Building data with 3D attributes
- **editors**: Editor information

### Materialized Views
- **building_stats**: Aggregated building statistics
- **building_type_stats**: Statistics by building type
- **building_3d_coverage**: 3D data coverage indicators

### Building Data Schema (building_history)
```sql
- building_id: Building identifier
- building_type: Building type (residential, apartments, etc.)
- height: Building height (meters)
- building_levels: Number of floors
- min_height: Minimum height (meters)
- building_levels_underground: Underground floors
- area_sqm: Area (square meters)
- prefcode: Prefecture code
- cityname: City/municipality name
- timestamp: Edit timestamp
- uid/username: Editor information
```

## 📈 Output Reports

Analysis results are saved as CSV files in the `reports` directory:

- `building_stats.csv`: Prefecture-level building statistics
- `building_type_stats.csv`: Statistics by building type
- `3d_coverage.csv`: 3D data coverage metrics
- `editor_stats.csv`: Editor statistics
- `area_stats.csv`: Building area analysis
- `monthly_activity.csv`: Monthly editing activity
- `prefecture_analysis.csv`: Detailed prefecture analysis

## 🎯 Technical Highlights

### High-Precision Area Calculation
Multiple calculation methods were compared and validated to implement the optimal algorithm:
- Geodetic calculation using Geography type (highest precision)
- Corrected calculation in Web Mercator projection (correction factor 0.825)
- Scale factor approximation (fallback method)

### Efficient Data Processing
- Utilizes PostGIS spatial indexing
- Optimized aggregation with materialized views
- Batch processing for large datasets

## 🗺 Supported Data Formats

### Input
- **OSM Data**: PBF format (Protocolbuffer Binary Format)
- **Administrative Boundaries**: Shapefile with prefecture codes (`prefcode`)

### Output
- **CSV**: Statistical reports and analysis results
- **GeoPackage**: Cross-platform spatial data format
- **GeoParquet**: Column-oriented spatial data format (requires GDAL 3.5+)
- **FlatGeobuf**: Binary spatial data format optimized for streaming

## 🤝 Contributing

Pull requests and issue reports are welcome! For major changes, please open an issue first to discuss what you would like to change.

## 📄 License

This project is licensed under the [MIT License](LICENSE).

## 🙏 Acknowledgments & Citation

This research was supported by JSPS KAKENHI Grant Numbers 22K18505, 24K21643, and 24K15662.

If you use this research, please cite:

Seto, T.: Analysis of Building 3D Attribute Coverage and Spatial Disparity of Editing Activities in OpenStreetMap, International Archives of the Photogrammetry, Remote Sensing and Spatial Information Sciences, 1–7, 2025.

This documentation was created with assistance from Claude Sonnet 4.

For questions or issues, please report them on the GitHub Issues page.
