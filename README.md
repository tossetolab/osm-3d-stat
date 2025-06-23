# osm-3d-stat

## 1. 概要

OpenStreetMap(OSM)から建物データを抽出し、特に3D属性（高さ・階数など）を分析するパイプラインを作成しました。このドキュメントでは、一連の処理プロセスと各ステップの技術的な詳細を説明します。

## 2. プロセスの流れ

処理は大きく分けて2つのフェーズに分かれています：

1. **データ抽出とインポート**（`import_osm_buildings.sh`）
2. **データ分析と可視化**（`building_analysis.py`）
3. **データの出力** (`export_buildings.sh`)

## 3. 環境準備

### 必要なソフトウェア

- PostgreSQL 13以上（PostGIS拡張機能必須）
- Python 3.7以上
  - pip install geopandas sqlalchemy psycopg2-binary pyogrio
- osm2pgsql（OSMデータインポート用）
- GDAL/OGR（行政区域データ処理用）

### 入力データ

- **OSMデータ**: `japan-250201-internal.osm.pbf`（または任意のOSM PBFファイル）
- **行政区域データ**: `N03-23_230101.shp`（都道府県コード`prefcode`を含むシェープファイル）

## 4. データ抽出とインポート

### 4.1 処理ステップ

`import_osm_buildings.sh`スクリプトは以下の処理を実行します：

1. PostgreSQLデータベースの作成
2. PostGIS・hstore拡張機能の有効化
3. 基本テーブルスキーマの作成（admin_boundaries, editors, building_history）
4. 行政区域データのインポート
5. OSMデータのインポート
6. 建物データの抽出と正確な面積計算
7. 編集者情報の更新
8. 分析用ビューの更新

### 4.2 正確な面積計算

建物面積の正確な計算方法は、複数の方法を比較検証し、最適な方法を実装しました：

```
CASE
    -- 方法1: geography型で計算（最も正確）
    WHEN ST_Area(geography(way)) > 0 THEN ST_Area(geography(way))

    -- 方法2: Web Mercatorで計算（補正係数適用）
    WHEN ST_Area(ST_Transform(way, 3857)) > 0 THEN
        ST_Area(ST_Transform(way, 3857)) * 0.825

    -- 方法3: 元の面積に縮尺係数を適用（最終手段）
    WHEN way_area > 0 THEN way_area * 10000000

    ELSE NULL
END AS area_sqm
```

テスト結果から、Web Mercator座標系は測地線計算（geography型）と比較して約21%大きな値になるため、0.825の補正係数を適用しています。

### 4.3 実行方法

```bash
./import_osm_buildings.sh osm_3ddata_analysis postgres N03-23_230101.shp japan-250201-internal.osm.pbf
```

オプションで処理件数を制限できます：

```bash
./import_osm_buildings.sh osm_3ddata_analysis postgres N03-23_230101.shp japan-250201-internal.osm.pbf 10000
```

## 5. データ分析

### 5.1 分析スクリプトの概要

`building_analysis.py`スクリプトは以下の処理を行います：

1. データベースへの接続
2. 各種統計情報の計算
3. 集中度指標（ジニ係数、HHI）の算出
4. レポートの生成とCSV出力
5. サマリー情報の表示

### 5.2 主要な分析内容

- **建物タイプごとの統計**: 建物タイプ別の分布、高さ・階数の平均値
- **都道府県別の3Dデータカバレッジ**: 高さ情報や階数情報の有無の割合
- **建物面積の分布**: 小・中・大規模建物の割合
- **編集者統計**: 編集者ごとの貢献パターン
- **編集集中度**: 都道府県別の編集集中度（ジニ係数・HHI）
- **月別活動**: 時系列での建物データ編集傾向

### 5.3 実行方法

```bash
python building_analysis.py --dbname osm_3ddata_analysis --user postgres --debug
```

## 6. データベース構造

### 6.1 メインテーブル

- **admin_boundaries**: 行政区域データ
- **building_history**: 建物データと3D属性
- **editors**: 編集者情報

### 6.2 マテリアライズドビュー

- **building_stats**: 建物データの集計
- **building_type_stats**: 建物タイプごとの統計
- **building_3d_coverage**: 3Dデータカバレッジ指標

### 6.3 建物データスキーマ（building_history）

```
- building_id: 建物ID
- building_type: 建物タイプ（residential, apartments等）
- height: 建物の高さ（m）
- building_levels: 建物の階数
- min_height: 最低高さ（m）
- building_levels_underground: 地下階数
- area_sqm: 面積（㎡）
- prefcode: 都道府県コード
- cityname: 市区町村名
- timestamp: 編集日時
- uid/username: 編集者情報
...その他のOSM属性
```

## 7. 出力レポート

分析結果は`reports`ディレクトリに以下のCSVファイルとして保存されます：

1. **building_stats**: 都道府県別の建物統計
2. **building_type_stats**: 建物タイプごとの詳細統計
3. **3d_coverage**: 3Dデータカバレッジ指標
4. **editor_stats**: 編集者別の統計
5. **area_stats**: 建物面積の分析
6. **monthly_activity**: 時系列での編集活動
7. **prefecture_analysis**: 都道府県別の詳細分析

## 8. データの出力

 `export_buildings.sh`は、GISデータとして出力したい場合に使用します。

### 8.1 概要

- GeoParquet固有の最適設定
  - `OGR_PARQUET_GEOMETRY_ENCODING WKB` - バイナリ形式で地理情報を保存（効率的）
  - `OGR_PARQUET_GEOMETRY_NAME geom` - 地理情報カラム名の指定
  - `COMPRESSION=ZSTD` - 高性能なZSTD圧縮アルゴリズムを使用
  - `ZSTD_COMPRESSION_LEVEL=3` - 圧縮率と速度のバランスが良いレベル
- 注意事項：GeoParquet形式を使用するには、GDAL 3.5以上が必要です。古いバージョンではサポートされていない可能性があります。

### 8.2 実行方法

```bash
# 基本的な使用法（デフォルトでGeoPackage形式）
./export_buildings.sh
# すべてのパラメータを指定
./export_buildings.sh osm_3ddata_analysis postgres gpkg buildings.gpkg

# FlatGeobuf形式で出力
./export_buildings.sh osm_3ddata_analysis postgres fgb buildings.fgb

# フィルタを追加（引用符を忘れずに）
./export_buildings_ogr.sh osm_3ddata_analysis postgres gpkg tall_buildings.gpkg "height > 50"
```

## 9. クレジット
* 本研究は、JSPS科研費（22K18505・23K22036・24K15662）の助成を受けて行いました。
* 本ドキュメントは，Calude 3.7 Sonnetを利用して作成しました。
