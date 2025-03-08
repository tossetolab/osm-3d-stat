#!/bin/bash

# エラーハンドリング
set -e

# カラー出力
function print_header() { echo -e "\033[1;34m==== $1 ====\033[0m"; }
function print_success() { echo -e "\033[1;32m✓ $1\033[0m"; }
function print_warning() { echo -e "\033[1;33m⚠ $1\033[0m"; }
function print_error() { echo -e "\033[1;31m✗ $1\033[0m"; }

# デフォルト値設定
DB_NAME=${1:-"osm_3ddata_analysis"}
DB_USER=${2:-"postgres"}
OUTPUT_FORMAT=${3:-"gpkg"}  # gpkg または fgb
OUTPUT_FILE=${4:-"building_export.${OUTPUT_FORMAT}"}
WHERE_CLAUSE=${5:-""}

print_header "building_historyデータの大規模エクスポート"
echo "Database: $DB_NAME"
echo "User: $DB_USER"
echo "Output Format: $OUTPUT_FORMAT"
echo "Output File: $OUTPUT_FILE"
echo "Filter: ${WHERE_CLAUSE:-'(none)'}"
echo

# SQLクエリの構築
SQL_QUERY="SELECT id, building_id, version, uid, username, timestamp::text,
           building_type, height, min_height, building_levels, building_levels_underground,
           ele, start_date, source, name, prefcode, cityname, citycode,
           area_sqm, geom FROM building_history"

# WHERE句の追加（指定されている場合）
if [ -n "$WHERE_CLAUSE" ]; then
    SQL_QUERY="$SQL_QUERY WHERE $WHERE_CLAUSE"
fi

print_header "データ出力開始 (約2400万件のデータ)"
echo "このプロセスには時間がかかる場合があります..."

# 出力形式設定
if [ "$OUTPUT_FORMAT" = "gpkg" ]; then
    DRIVER="GPKG"
    echo "GeoPackage形式で出力します"
elif [ "$OUTPUT_FORMAT" = "fgb" ]; then
    DRIVER="FlatGeobuf"
    echo "FlatGeobuf形式で出力します"
else
    print_error "サポートされていない出力形式です: $OUTPUT_FORMAT"
    exit 1
fi

# ogr2ogrによるエクスポート（効率化オプション有効）
time ogr2ogr -f "$DRIVER" \
    "$OUTPUT_FILE" \
    PG:"dbname=$DB_NAME user=$DB_USER" \
    -sql "$SQL_QUERY" \
    -a_srs "EPSG:4326" \
    -progress \
    --config PG_USE_COPY YES \
    --config OGR_ENABLE_PARTIAL_REPROJECTION YES \
    --config CPL_TMPDIR /tmp \
    -gt 65536 \
    --debug ON

if [ $? -eq 0 ]; then
    print_success "エクスポート完了: $OUTPUT_FILE"
    # ファイルサイズの表示
    FILE_SIZE=$(du -h "$OUTPUT_FILE" | cut -f1)
    echo "ファイルサイズ: $FILE_SIZE"
else
    print_error "エクスポート失敗"
    exit 1
fi
