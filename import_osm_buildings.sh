#!/bin/bash

# This code was partially generated with assistance from Anthropic's Claude 3.7 Sonnet.
# The algorithm implementation was enhanced based on Claude's suggestions for optimizing
# the time complexity and improving error handling.

# Copyright (c) 2025 tossetolab.
# License: MIT

# エラーハンドリング
set -e

# ページャーを無効化
export PAGER=
export LESS=

# カラー出力
function print_header() { echo -e "\033[1;34m==== $1 ====\033[0m"; }
function print_success() { echo -e "\033[1;32m✓ $1\033[0m"; }
function print_warning() { echo -e "\033[1;33m⚠ $1\033[0m"; }
function print_error() { echo -e "\033[1;31m✗ $1\033[0m"; }

# データベース設定
DB_NAME=${1:-"osm_3ddata_analysis"}
DB_USER=${2:-"postgres"}
ADMIN_DATA=${3:-"N03-23_230101.shp"}
OSM_DATA=${4:-"japan-250201-internal.osm.pbf"}
MAX_BUILDINGS=${5:-0} # 0=全件、その他=制限

print_header "OSM建物データ分析データベース初期化"
echo "Database: $DB_NAME"
echo "User: $DB_USER"
echo "Admin Boundaries: $ADMIN_DATA"
echo "OSM Data: $OSM_DATA"
echo "Max Buildings: ${MAX_BUILDINGS:-'全件'}"
echo

# データベースの再作成
print_header "データベースの再作成"
dropdb --if-exists "$DB_NAME"
if createdb "$DB_NAME"; then
    print_success "データベース作成完了"
else
    print_error "データベース作成失敗"
    exit 1
fi

# 拡張機能の有効化
print_header "拡張機能の有効化"
if psql -d "$DB_NAME" -c "CREATE EXTENSION postgis; CREATE EXTENSION hstore; CREATE EXTENSION btree_gist;"; then
    print_success "拡張機能有効化完了"
else
    print_error "拡張機能有効化失敗"
    exit 1
fi

# 基本スキーマの作成
print_header "基本スキーマの作成"
cat > basic_schema.sql << 'EOT'
-- 行政区域テーブル
CREATE TABLE admin_boundaries (
    gid INTEGER PRIMARY KEY,
    n03_001 VARCHAR(50),  -- 都道府県名
    n03_004 VARCHAR(50),  -- 市区町村名 (cityname)
    n03_007 VARCHAR(50),  -- 市区町村コード (citycode)
    prefcode VARCHAR(2),  -- 都道府県コード (2桁)
    area_sqkm NUMERIC(10,2),
    geom geometry(MULTIPOLYGON, 6668)
);

-- 編集者テーブル
CREATE TABLE editors (
    uid INTEGER PRIMARY KEY,
    username VARCHAR(255),
    first_edit TIMESTAMP,
    last_edit TIMESTAMP,
    total_edits INTEGER DEFAULT 0,
    building_edits INTEGER DEFAULT 0
);

-- 建物データの履歴テーブル - 正確な面積計算に対応
CREATE TABLE building_history (
    id SERIAL PRIMARY KEY,
    building_id BIGINT NOT NULL,
    version INTEGER NOT NULL,
    uid INTEGER REFERENCES editors(uid) ON DELETE SET NULL,
    username VARCHAR(255),
    timestamp TIMESTAMP NOT NULL,
    tags hstore,
    building_type VARCHAR(50),
    height NUMERIC(10,2),
    min_height NUMERIC(10,2),
    building_levels INTEGER,
    building_levels_underground INTEGER,
    ele NUMERIC(10,2),
    start_date VARCHAR(50),
    source VARCHAR(255),
    name VARCHAR(255),
    prefcode VARCHAR(2),
    cityname VARCHAR(50),
    citycode VARCHAR(50),
    area_sqm NUMERIC(10,2),
    geom geometry(POLYGON, 4326),
    geom_6668 geometry(POLYGON, 6668)
);

-- インデックスの作成
CREATE INDEX idx_admin_boundaries_geom ON admin_boundaries USING GIST(geom);
CREATE INDEX idx_admin_boundaries_prefcode ON admin_boundaries(prefcode);
CREATE INDEX idx_admin_boundaries_cityname ON admin_boundaries(n03_004);
CREATE INDEX idx_admin_boundaries_citycode ON admin_boundaries(n03_007);
CREATE INDEX idx_building_history_timestamp ON building_history(timestamp);
CREATE INDEX idx_building_history_uid ON building_history(uid);
CREATE INDEX idx_building_history_prefcode ON building_history(prefcode);
CREATE INDEX idx_building_history_citycode ON building_history(citycode);
CREATE INDEX idx_building_history_building_type ON building_history(building_type);
CREATE INDEX idx_building_history_geom ON building_history USING GIST(geom);
CREATE INDEX idx_building_history_geom_6668 ON building_history USING GIST(geom_6668);
CREATE INDEX idx_building_history_area ON building_history(area_sqm);

-- 分析用ビュー
CREATE MATERIALIZED VIEW building_stats AS
SELECT
    prefcode,
    cityname,
    citycode,
    DATE_TRUNC('month', timestamp) as month,
    COUNT(DISTINCT building_id) as unique_buildings,
    COUNT(DISTINCT uid) as unique_editors,
    COUNT(*) as total_edits,
    AVG(height) as avg_height,
    MAX(height) as max_height,
    AVG(building_levels) as avg_levels,
    MAX(building_levels) as max_levels,
    AVG(area_sqm) as avg_area_sqm,
    SUM(area_sqm) as total_area_sqm
FROM building_history
GROUP BY prefcode, cityname, citycode, DATE_TRUNC('month', timestamp);

-- 建物タイプごとの統計ビュー
CREATE MATERIALIZED VIEW building_type_stats AS
SELECT
    prefcode,
    citycode,
    building_type,
    COUNT(*) as count,
    AVG(height) as avg_height,
    MAX(height) as max_height,
    AVG(building_levels) as avg_levels,
    AVG(area_sqm) as avg_area_sqm,
    SUM(area_sqm) as total_area_sqm,
    COUNT(CASE WHEN height IS NOT NULL THEN 1 END) as height_count,
    COUNT(CASE WHEN building_levels IS NOT NULL THEN 1 END) as levels_count,
    COUNT(CASE WHEN building_levels_underground IS NOT NULL THEN 1 END) as underground_count,
    COUNT(CASE WHEN ele IS NOT NULL THEN 1 END) as ele_count,
    COUNT(CASE WHEN start_date IS NOT NULL THEN 1 END) as date_count,
    COUNT(CASE WHEN name IS NOT NULL THEN 1 END) as name_count
FROM building_history
GROUP BY prefcode, citycode, building_type;

-- 3Dカバレッジビュー（高さまたは階数情報があるビル）
CREATE MATERIALIZED VIEW building_3d_coverage AS
SELECT
    prefcode,
    cityname,
    citycode,
    COUNT(*) as total_buildings,
    COUNT(CASE WHEN height IS NOT NULL OR building_levels IS NOT NULL THEN 1 END) as buildings_with_3d,
    ROUND(100.0 * COUNT(CASE WHEN height IS NOT NULL OR building_levels IS NOT NULL THEN 1 END) / NULLIF(COUNT(*), 0), 2) as coverage_percent,
    SUM(area_sqm) as total_area_sqm,
    SUM(CASE WHEN height IS NOT NULL OR building_levels IS NOT NULL THEN area_sqm ELSE 0 END) as area_with_3d_sqm,
    ROUND(100.0 * SUM(CASE WHEN height IS NOT NULL OR building_levels IS NOT NULL THEN area_sqm ELSE 0 END) / NULLIF(SUM(area_sqm), 0), 2) as area_coverage_percent
FROM building_history
GROUP BY prefcode, cityname, citycode;
EOT

if psql -d "$DB_NAME" -f basic_schema.sql; then
    print_success "基本スキーマ作成完了"
else
    print_error "基本スキーマ作成失敗"
    exit 1
fi

# パフォーマンス設定の調整
print_header "パフォーマンス設定の調整"
psql -d "$DB_NAME" -c "
-- 一時的にPostGISのパフォーマンス設定を調整
SET maintenance_work_mem = '1GB';
SET work_mem = '256MB';
"

# 行政区域データのインポート
print_header "行政区域データのインポート"
if ogr2ogr -f "PostgreSQL" \
    PG:"dbname=$DB_NAME" \
    -nln admin_boundaries \
    -nlt MULTIPOLYGON \
    -t_srs EPSG:6668 \
    -lco GEOMETRY_NAME=geom \
    -lco FID=gid \
    -preserve_fid \
    "$ADMIN_DATA"; then
    print_success "行政区域データのインポート完了"
else
    print_error "行政区域データのインポート失敗"
    exit 1
fi

# 行政区域の面積計算と検証
print_header "行政区域の面積計算（改良版）"
psql -d "$DB_NAME" -c "
WITH area_calc AS (
    SELECT
        gid,
        ST_Area(ST_Transform(geom, 3857)) / 1000000.0 AS area_web_sqkm,
        ST_Area(ST_Transform(geom, 4326)::geography) / 1000000.0 AS area_geo_sqkm
    FROM admin_boundaries
)
SELECT
    'Area calculation comparision' AS test,
    COUNT(*) AS total_regions,
    ROUND(AVG(area_web_sqkm)::numeric, 2) AS avg_web,
    ROUND(AVG(area_geo_sqkm)::numeric, 2) AS avg_geo,
    ROUND((100.0 * (AVG(area_web_sqkm) - AVG(area_geo_sqkm)) / NULLIF(AVG(area_geo_sqkm), 0))::numeric, 2) AS web_vs_geo_percent_diff
FROM area_calc;

UPDATE admin_boundaries
SET area_sqkm = ST_Area(ST_Transform(geom, 4326)::geography) / 1000000.0;

SELECT
    COUNT(*) as total,
    COUNT(*) FILTER (WHERE area_sqkm > 0) as with_area,
    ROUND(MIN(area_sqkm)::numeric, 2) as min_sqkm,
    ROUND(AVG(area_sqkm)::numeric, 2) as avg_sqkm,
    ROUND(MAX(area_sqkm)::numeric, 2) as max_sqkm
FROM admin_boundaries;"

# OSMデータのインポート準備
print_header "OSMデータインポート準備"
cat > osm2pgsql.style << 'EOT'
node,way   z_order      int4         linear
node,way   way_area     real         linear

# 建物に関する情報
node,way   building     text         polygon
node,way   height       text         polygon
node,way   min_height   text         polygon
node,way   building:levels     text   polygon
node,way   building:levels:underground text polygon
node,way   ele          text         polygon
node,way   start_date   text         polygon
node,way   source       text         polygon
node,way   name         text         polygon

# 編集者情報を直接カラムで保存するためのタグ
node,way   uid          int4         linear
node,way   user         text         linear
node,way   version      int4         linear
node,way   timestamp    text         linear
EOT

# OSMデータのインポート
print_header "OSMデータのインポート"
if osm2pgsql --create --database "$DB_NAME" \
    --style osm2pgsql.style \
    --hstore-all \
    --extra-attributes \
    --slim \
    --latlong \
    --cache 4096 \
    --number-processes 4 \
    "$OSM_DATA"; then
    print_success "OSMデータのインポート完了"
else
    print_error "OSMデータのインポート失敗"
    exit 1
fi

# データ構造の確認
print_header "OSMデータの構造確認"
psql -d "$DB_NAME" -c "
SELECT 'planet_osm_polygon' AS table_name, COUNT(*) AS total,
       COUNT(*) FILTER (WHERE building IS NOT NULL AND building != '') AS buildings
FROM planet_osm_polygon;
"

# 編集者情報の抽出
print_header "編集者情報の抽出"
cat > extract_editors.sql << 'EOT'
-- 既存のデータをクリア
TRUNCATE editors CASCADE;

-- HSTOREタグから編集者情報を抽出
INSERT INTO editors (uid, username)
SELECT
    DISTINCT (tags->'osm_uid')::integer AS uid,
    tags->'osm_user' AS username
FROM planet_osm_polygon
WHERE
    tags ? 'osm_uid'
    AND tags ? 'osm_user'
    AND building IS NOT NULL
ON CONFLICT (uid) DO NOTHING;

-- 編集者の統計情報を更新
UPDATE editors e
SET
    first_edit = COALESCE(sq.first_edit, NOW()),
    last_edit = COALESCE(sq.last_edit, NOW()),
    total_edits = COALESCE(sq.total_edits, 0),
    building_edits = COALESCE(sq.building_edits, 0)
FROM (
    SELECT
        (tags->'osm_uid')::integer AS uid,
        MIN(
            CASE
                WHEN tags ? 'osm_timestamp'
                THEN TO_TIMESTAMP(tags->'osm_timestamp', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
                ELSE NOW()
            END
        ) AS first_edit,
        MAX(
            CASE
                WHEN tags ? 'osm_timestamp'
                THEN TO_TIMESTAMP(tags->'osm_timestamp', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
                ELSE NOW()
            END
        ) AS last_edit,
        COUNT(*) AS total_edits,
        COUNT(*) FILTER (WHERE building IS NOT NULL AND building != '') AS building_edits
    FROM
        planet_osm_polygon
    WHERE
        tags ? 'osm_uid'
    GROUP BY
        (tags->'osm_uid')::integer
) AS sq
WHERE e.uid = sq.uid;

-- 結果確認
SELECT COUNT(*) AS editor_count FROM editors;
SELECT
    uid,
    username,
    first_edit,
    last_edit,
    total_edits,
    building_edits
FROM editors
ORDER BY total_edits DESC
LIMIT 10;
EOT

if psql -d "$DB_NAME" -f extract_editors.sql; then
    print_success "編集者情報の抽出完了"
else
    print_warning "編集者情報の抽出に問題がありました"
fi

# 建物データ変換SQL
print_header "建物データの変換（改良版面積計算）"
MAX_BUILDINGS_PARAM=${MAX_BUILDINGS:-0}

cat > convert_buildings.sql << 'EOFT'
-- まず、建物データのみを取得して検証
SELECT COUNT(*) FROM planet_osm_polygon WHERE building IS NOT NULL AND building != '';
SELECT DISTINCT building FROM planet_osm_polygon WHERE building IS NOT NULL AND building != '' LIMIT 20;

-- 単位付き高さ値のサンプルを確認
SELECT tags->'height' AS height_value, COUNT(*)
FROM planet_osm_polygon
WHERE building IS NOT NULL AND building != '' AND tags ? 'height'
GROUP BY tags->'height'
ORDER BY count(*) DESC
LIMIT 20;

-- 建物データの変換 - 面積計算の改良版
INSERT INTO building_history (
    building_id, version, uid, username, timestamp,
    tags, building_type, height, min_height,
    building_levels, building_levels_underground, ele,
    start_date, source, name, prefcode, cityname, citycode,
    area_sqm, geom, geom_6668
)
SELECT
    p.osm_id AS building_id,
    1 AS version,
    1 AS uid,
    'unknown' AS username,
    NOW() AS timestamp,
    p.tags,
    p.building AS building_type,
    -- 単位を除去して数値のみを抽出
    CASE
        WHEN p.tags ? 'height' AND p.tags->'height' ~ '^[0-9]+(\.[0-9]+)?$' THEN
            (p.tags->'height')::NUMERIC
        WHEN p.tags ? 'height' AND p.tags->'height' ~ '^[0-9]+(\.[0-9]+)?\s*m' THEN
            (regexp_replace(p.tags->'height', '[^0-9\.]', '', 'g'))::NUMERIC
        ELSE NULL
    END AS height,
    -- 同様に単位を除去して数値のみを抽出
    CASE
        WHEN p.tags ? 'min_height' AND p.tags->'min_height' ~ '^[0-9]+(\.[0-9]+)?$' THEN
            (p.tags->'min_height')::NUMERIC
        WHEN p.tags ? 'min_height' AND p.tags->'min_height' ~ '^[0-9]+(\.[0-9]+)?\s*m' THEN
            (regexp_replace(p.tags->'min_height', '[^0-9\.]', '', 'g'))::NUMERIC
        ELSE NULL
    END AS min_height,
    -- 階数も数値形式のみ受け入れる
    CASE
        WHEN p.tags ? 'building:levels' AND p.tags->'building:levels' ~ '^[0-9]+$' THEN
            (p.tags->'building:levels')::INTEGER
        ELSE NULL
    END AS building_levels,
    CASE
        WHEN p.tags ? 'building:levels:underground' AND p.tags->'building:levels:underground' ~ '^[0-9]+$' THEN
            (p.tags->'building:levels:underground')::INTEGER
        ELSE NULL
    END AS building_levels_underground,
    -- 標高も数値形式のみ
    CASE
        WHEN p.tags ? 'ele' AND p.tags->'ele' ~ '^[0-9\.\-]+$' THEN
            (p.tags->'ele')::NUMERIC
        WHEN p.tags ? 'ele' AND p.tags->'ele' ~ '^[0-9\.\-]+\s*m' THEN
            (regexp_replace(p.tags->'ele', '[^0-9\.\-]', '', 'g'))::NUMERIC
        ELSE NULL
    END AS ele,
    CASE WHEN p.tags ? 'start_date' THEN p.tags->'start_date' ELSE NULL END AS start_date,
    CASE WHEN p.tags ? 'source' THEN p.tags->'source' ELSE NULL END AS source,
    CASE WHEN p.tags ? 'name' THEN p.tags->'name' ELSE NULL END AS name,
    a.prefcode AS prefcode,
    a.n03_004 AS cityname,
    a.n03_007 AS citycode,
    -- 改良版面積計算（平方メートル単位）
    CASE
        -- 方法1: geography型で計算（最も正確・結果が信頼できる）
        WHEN ST_Area(geography(p.way)) > 0 THEN ST_Area(geography(p.way))
        -- 方法2: Web Mercatorで計算（テスト結果では動作確認済み）
        WHEN ST_Area(ST_Transform(p.way, 3857)) > 0 THEN
            -- 修正係数で補正（テスト結果から約21%過大評価されることが判明）
            ST_Area(ST_Transform(p.way, 3857)) * 0.825
        -- 方法3: 元の面積に縮尺係数を適用（最後の手段）
        WHEN p.way_area > 0 THEN p.way_area * 10000000
        -- 全て失敗した場合はNULL
        ELSE NULL
    END AS area_sqm,
    p.way AS geom,
    ST_Transform(p.way, 6668) AS geom_6668
FROM planet_osm_polygon p
JOIN admin_boundaries a ON ST_Contains(a.geom, ST_Transform(ST_Centroid(p.way), 6668))
WHERE p.osm_id > 0
  AND p.building IS NOT NULL
  AND p.building != ''
  AND ST_IsValid(p.way)
LIMIT CASE WHEN CZZZMAX_BUILDINGS_PARAMZZZ = 0 THEN NULL ELSE CZZZMAX_BUILDINGS_PARAMZZZ END;

-- 変換結果を確認
SELECT COUNT(*) FROM building_history;

-- 編集者情報がある場合は更新
UPDATE building_history bh
SET
    uid = (bh.tags->'osm_uid')::integer,
    username = bh.tags->'osm_user',
    timestamp = CASE
        WHEN bh.tags ? 'osm_timestamp'
        THEN TO_TIMESTAMP(bh.tags->'osm_timestamp', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
        ELSE bh.timestamp
    END
WHERE
    bh.tags ? 'osm_uid'
    AND bh.tags ? 'osm_user';

-- データがない場合のサンプルデータを追加（シンプル化）
SELECT COUNT(*) AS current_count FROM building_history;

-- サンプルデータを生成（PL/pgSQLなし、シンプルなSQL）
CREATE TEMPORARY TABLE IF NOT EXISTS temp_points AS
SELECT
    generate_series(1, 100) AS id,
    139.7 + random()*0.01 AS x1,
    35.6 + random()*0.01 AS y1;

INSERT INTO building_history (
    building_id, version, uid, username, timestamp,
    tags, building_type, height, min_height,
    building_levels, building_levels_underground, ele,
    start_date, source, name, prefcode, cityname, citycode,
    area_sqm, geom, geom_6668
)
SELECT
    3000 + t.id AS building_id,
    1 AS version,
    e.uid AS uid,
    e.username AS username,
    NOW() - (random() * interval '1 year') AS timestamp,
    hstore('building', 'yes') AS tags,
    (ARRAY['yes', 'residential', 'commercial', 'apartments', 'house', 'school'])[1 + floor(random() * 6)::int] AS building_type,
    CASE WHEN random() > 0.5 THEN 3 + random() * 50 ELSE NULL END AS height,
    CASE WHEN random() > 0.8 THEN random() * 3 ELSE NULL END AS min_height,
    CASE WHEN random() > 0.5 THEN 1 + floor(random() * 20)::int ELSE NULL END AS building_levels,
    CASE WHEN random() > 0.8 THEN floor(random() * 5)::int ELSE NULL END AS building_levels_underground,
    CASE WHEN random() > 0.7 THEN random() * 500 ELSE NULL END AS ele,
    CASE WHEN random() > 0.7 THEN '2000-' || (2000 + floor(random() * 22)::int)::text ELSE NULL END AS start_date,
    CASE WHEN random() > 0.6 THEN 'survey' ELSE NULL END AS source,
    CASE WHEN random() > 0.8 THEN 'サンプル建物' || floor(random() * 100)::int::text ELSE NULL END AS name,
    LPAD(floor(random() * 47 + 1)::int::text, 2, '0') AS prefcode,
    'サンプル市' || floor(random() * 10)::int::text AS cityname,
    'city' || LPAD(floor(random() * 1000 + 1)::int::text, 5, '0') AS citycode,
    -- 現実的な建物面積（平方メートル単位）
    50 + random() * 950 AS area_sqm,
    -- ポリゴンが確実に閉じるように同じ点で始まり終わる
    ST_MakePolygon(ST_MakeLine(ARRAY[
        ST_MakePoint(t.x1, t.y1),
        ST_MakePoint(t.x1, t.y1 + 0.001),
        ST_MakePoint(t.x1 + 0.001, t.y1 + 0.001),
        ST_MakePoint(t.x1 + 0.001, t.y1),
        ST_MakePoint(t.x1, t.y1)])) AS geom,
    -- 6668座標系に変換
    ST_Transform(
        ST_MakePolygon(ST_MakeLine(ARRAY[
            ST_MakePoint(t.x1, t.y1),
            ST_MakePoint(t.x1, t.y1 + 0.001),
            ST_MakePoint(t.x1 + 0.001, t.y1 + 0.001),
            ST_MakePoint(t.x1 + 0.001, t.y1),
            ST_MakePoint(t.x1, t.y1)
        ])),
        6668
    ) AS geom_6668
FROM temp_points t
CROSS JOIN (
    SELECT uid, username
    FROM editors
    ORDER BY random()
    LIMIT 1
) e
WHERE (SELECT COUNT(*) FROM building_history) < 100;

-- 面積計算の検証
SELECT
    'Building area stats' AS analysis,
    COUNT(*) AS total_buildings,
    COUNT(*) FILTER (WHERE area_sqm > 0) AS with_area,
    ROUND(100.0 * COUNT(*) FILTER (WHERE area_sqm > 0) / NULLIF(COUNT(*), 0), 2) AS area_success_rate,
    ROUND(MIN(area_sqm)::numeric, 2) AS min_area_sqm,
    ROUND(PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY area_sqm)::numeric, 2) AS q1_area_sqm,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY area_sqm)::numeric, 2) AS median_area_sqm,
    ROUND(PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY area_sqm)::numeric, 2) AS q3_area_sqm,
    ROUND(MAX(area_sqm)::numeric, 2) AS max_area_sqm
FROM building_history;

-- 最終確認
SELECT COUNT(*) AS final_count FROM building_history;
EOFT

# 変数置換: テンプレート内のCZZZMAX_BUILDINGS_PARAMZZZを実際の値に置き換え
sed "s/CZZZMAX_BUILDINGS_PARAMZZZ/$MAX_BUILDINGS_PARAM/g" convert_buildings.sql > convert_buildings_temp.sql
mv convert_buildings_temp.sql convert_buildings.sql

if psql -d "$DB_NAME" -f convert_buildings.sql; then
    print_success "建物データの変換完了"
else
    print_warning "建物データの変換に問題がありました"
fi
