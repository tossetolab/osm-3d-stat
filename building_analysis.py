# Copyright (c) 2025 tossetolab.
# License: MIT

import argparse
import os
import sys
import warnings
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import geopandas as gpd
import numpy as np
import pandas as pd
import psycopg2

warnings.filterwarnings("ignore")


@dataclass
class DBConfig:
    """データベース接続設定"""

    dbname: str = "osm_3ddata_analysis"
    user: str = "postgres"
    password: str = ""
    host: str = "localhost"
    port: str = "5432"


def calculate_gini(values: np.ndarray) -> float:
    """ジニ係数を計算する関数"""
    if len(values) <= 1:
        return 0
    sorted_values = np.sort(values)
    n = len(values)
    index = np.arange(1, n + 1)
    return ((2 * index - n - 1) * sorted_values).sum() / (n * sorted_values.sum())


def calculate_hhi(shares: np.ndarray) -> float:
    """HHI（ハーフィンダール・ハーシュマン指数）を計算する関数"""
    return np.sum(np.square(shares))


class BuildingDataAnalyzer:
    def __init__(self, config: DBConfig, debug=False):
        self.config = config
        self.conn = None
        self.debug = debug

    def connect(self):
        """データベースに接続"""
        if not self.conn:
            try:
                self.conn = psycopg2.connect(
                    dbname=self.config.dbname,
                    user=self.config.user,
                    password=self.config.password,
                    host=self.config.host,
                    port=self.config.port,
                )
                if self.debug:
                    print(f"✅ Connected to database {self.config.dbname}")
            except Exception as e:
                print(f"❌ Database connection error: {str(e)}")
                raise
        return self.conn

    def close(self):
        """データベース接続を閉じる"""
        if self.conn:
            self.conn.close()
            self.conn = None
            if self.debug:
                print("✅ Database connection closed")

    def execute_query(self, query, params=None):
        """SQL実行とエラーハンドリング"""
        try:
            if self.debug:
                print(f"🔍 Executing query: {query[:100]}...")

            result = pd.read_sql(query, self.connect(), params=params)

            if self.debug:
                print(f"✅ Query executed, returned {len(result)} rows")

            return result
        except Exception as e:
            print(f"❌ Query execution error: {str(e)}")
            if self.debug:
                print(f"Query was: {query}")
            raise

    def check_tables_exist(self):
        """必要なテーブルが存在するか確認"""
        tables_to_check = ["editors", "building_history", "admin_boundaries"]

        check_query = """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = ANY(%s)
        """
        existing_tables = self.execute_query(check_query, [tables_to_check])
        found_tables = existing_tables["table_name"].tolist()

        print("\n=== Database Table Check ===")
        for table in tables_to_check:
            status = "✅" if table in found_tables else "❌"
            print(f"{status} {table}")

        if len(found_tables) < len(tables_to_check):
            missing = [t for t in tables_to_check if t not in found_tables]
            print(f"\n⚠️ Missing tables: {', '.join(missing)}")
            return False
        return True

    def get_building_statistics(self) -> pd.DataFrame:
        """
        建物データの統計情報を取得（citycode単位で集計）
        building_historyテーブルのcitycode、prefcode、citynameをそのまま使用し、
        admin_boundariesから面積情報を取得
        """
        query = """
        WITH building_data AS (
            -- building_historyからcitycode単位での建物数等を集計
            SELECT
                citycode,
                prefcode,
                cityname,
                COUNT(*) as building_count,
                COUNT(DISTINCT building_type) as building_types,
                ROUND(AVG(height)::numeric, 2) as avg_height,
                MAX(height) as max_height,
                ROUND(AVG(building_levels)::numeric, 2) as avg_levels,
                MAX(building_levels) as max_levels,
                ROUND(SUM(area_sqm)/10000.0, 4) as total_building_area_ha,
                ROUND(AVG(area_sqm)/10000.0, 4) as avg_building_area_ha,
                ROUND(MAX(area_sqm)/10000.0, 4) as max_building_area_ha,
                COUNT(CASE WHEN height IS NOT NULL THEN 1 END) as height_count,
                COUNT(CASE WHEN building_levels IS NOT NULL THEN 1 END) as levels_count,
                COUNT(CASE WHEN min_height IS NOT NULL THEN 1 END) as min_height_count,
                COUNT(CASE WHEN building_levels_underground IS NOT NULL THEN 1 END) as underground_count,
                COUNT(CASE WHEN ele IS NOT NULL THEN 1 END) as ele_count,
                COUNT(CASE WHEN start_date IS NOT NULL THEN 1 END) as date_count,
                COUNT(CASE WHEN source IS NOT NULL THEN 1 END) as source_count,
                COUNT(CASE WHEN name IS NOT NULL THEN 1 END) as name_count,
                COUNT(DISTINCT uid) as editor_count
            FROM
                building_history
            WHERE
                citycode IS NOT NULL
            GROUP BY
                citycode, prefcode, cityname
        ),
        area_data AS (
            -- admin_boundariesから行政区域の面積情報を取得
            SELECT
                n03_007 as citycode,
                ROUND(AVG(area_sqkm)::numeric, 2) * 100 as prefecture_area_ha
            FROM
                admin_boundaries
            WHERE
                n03_007 IS NOT NULL
            GROUP BY
                n03_007
        )
        -- 建物データと面積データを結合して最終的な結果を作成
        SELECT
            bd.citycode,
            bd.prefcode,
            bd.cityname,
            bd.building_count,
            bd.building_types,
            bd.avg_height,
            bd.max_height,
            bd.avg_levels,
            bd.max_levels,
            bd.total_building_area_ha,
            bd.avg_building_area_ha,
            bd.max_building_area_ha,
            bd.height_count,
            bd.levels_count,
            bd.min_height_count,
            bd.underground_count,
            bd.ele_count,
            bd.date_count,
            bd.source_count,
            bd.name_count,
            bd.editor_count,
            COALESCE(ad.prefecture_area_ha, 0) as prefecture_area_ha,
            CASE
                WHEN ad.prefecture_area_ha > 0
                THEN ROUND((bd.total_building_area_ha / ad.prefecture_area_ha * 100.0)::numeric, 2)
                ELSE 0
            END as building_coverage_percent
        FROM
            building_data bd
        LEFT JOIN
            area_data ad ON bd.citycode = ad.citycode
        ORDER BY
            bd.building_count DESC;
        """

        if self.debug:
            print("🔍 Getting building statistics by citycode with area calculation...")

        result = self.execute_query(query)

        if self.debug:
            print(f"✅ Found {len(result)} citycode building statistics")
            if not result.empty:
                print("\nDebug - First 5 rows:")
                pd.set_option("display.max_columns", None)
                print(result.head())
                pd.reset_option("display.max_columns")

        return result

    def get_building_type_statistics(self) -> pd.DataFrame:
        """建物タイプごとの統計情報を取得（area_sqmを使用）"""
        query = """
        SELECT
            building_type,
            COUNT(*) as count,
            ROUND(AVG(height)::numeric, 2) as avg_height,
            MAX(height) as max_height,
            ROUND(AVG(building_levels)::numeric, 2) as avg_levels,
            MAX(building_levels) as max_levels,
            ROUND(AVG(area_sqm)::numeric, 2) as avg_area_sqm,
            ROUND(MIN(area_sqm)::numeric, 2) as min_area_sqm,
            ROUND(MAX(area_sqm)::numeric, 2) as max_area_sqm,
            COUNT(CASE WHEN height IS NOT NULL THEN 1 END) as height_count,
            COUNT(CASE WHEN building_levels IS NOT NULL THEN 1 END) as levels_count,
            COUNT(CASE WHEN min_height IS NOT NULL THEN 1 END) as min_height_count,
            COUNT(CASE WHEN building_levels_underground IS NOT NULL THEN 1 END) as underground_count,
            COUNT(CASE WHEN ele IS NOT NULL THEN 1 END) as ele_count,
            COUNT(CASE WHEN start_date IS NOT NULL THEN 1 END) as date_count,
            COUNT(CASE WHEN source IS NOT NULL THEN 1 END) as source_count,
            COUNT(CASE WHEN name IS NOT NULL THEN 1 END) as name_count,
            COUNT(DISTINCT prefcode) as prefecture_count
        FROM building_history
        WHERE building_type IS NOT NULL AND building_type != ''
        GROUP BY building_type
        ORDER BY count DESC
        """

        if self.debug:
            print("🔍 Getting building type statistics...")

        result = self.execute_query(query)

        if self.debug:
            print(f"✅ Found {len(result)} building types")

        return result

    def get_building_area_analysis(self) -> pd.DataFrame:
        """建物面積に関する詳細分析（area_sqmを使用）"""
        query = """
        WITH area_stats AS (
            SELECT
                prefcode,
                building_type,
                COUNT(*) as building_count,
                ROUND(AVG(area_sqm)::numeric, 2) as avg_area_sqm,
                ROUND(MIN(area_sqm)::numeric, 2) as min_area_sqm,
                ROUND(MAX(area_sqm)::numeric, 2) as max_area_sqm,
                -- 面積区分ごとの集計
                COUNT(CASE WHEN area_sqm < 100 THEN 1 END) as small_buildings,
                COUNT(CASE WHEN area_sqm >= 100 AND area_sqm < 500 THEN 1 END) as medium_buildings,
                COUNT(CASE WHEN area_sqm >= 500 AND area_sqm < 1000 THEN 1 END) as large_buildings,
                COUNT(CASE WHEN area_sqm >= 1000 THEN 1 END) as extra_large_buildings
            FROM
                building_history
            WHERE
                area_sqm > 0
            GROUP BY
                prefcode,
                building_type
        )
        SELECT
            prefcode,
            building_type,
            building_count,
            avg_area_sqm,
            min_area_sqm,
            max_area_sqm,
            small_buildings,
            medium_buildings,
            large_buildings,
            extra_large_buildings,
            ROUND((small_buildings::numeric / NULLIF(building_count::numeric, 0)) * 100, 2) as small_percent,
            ROUND((medium_buildings::numeric / NULLIF(building_count::numeric, 0)) * 100, 2) as medium_percent,
            ROUND((large_buildings::numeric / NULLIF(building_count::numeric, 0)) * 100, 2) as large_percent,
            ROUND((extra_large_buildings::numeric / NULLIF(building_count::numeric, 0)) * 100, 2) as extra_large_percent
        FROM area_stats
        ORDER BY
            prefcode,
            building_count DESC
        """

        if self.debug:
            print("🔍 Analyzing building area statistics...")

        result = self.execute_query(query)

        if self.debug:
            print(
                f"✅ Analysis complete for {len(result)} building type/prefecture combinations"
            )

        return result

    def get_3d_data_coverage(self, level: str = "prefecture") -> pd.DataFrame:
        """3Dデータカバレッジの計算（level: 'prefecture'=都道府県単位 / 'city'=市区町村単位）"""
        if level == "city":
            group_columns = "citycode, prefcode, cityname"
            where_clause = "WHERE citycode IS NOT NULL"
        else:
            group_columns = "prefcode"
            where_clause = ""

        query = f"""
        SELECT
            {group_columns},
            COUNT(*) as total_buildings,
            COUNT(CASE WHEN height IS NOT NULL THEN 1 END) as height_count,
            COUNT(CASE WHEN building_levels IS NOT NULL THEN 1 END) as levels_count,
            COUNT(CASE WHEN min_height IS NOT NULL THEN 1 END) as min_height_count,
            COUNT(CASE WHEN building_levels_underground IS NOT NULL THEN 1 END) as underground_count,
            COUNT(CASE WHEN ele IS NOT NULL THEN 1 END) as ele_count,
            ROUND(COUNT(CASE WHEN height IS NOT NULL THEN 1 END)::numeric / COUNT(*) * 100, 2) as height_coverage,
            ROUND(COUNT(CASE WHEN building_levels IS NOT NULL THEN 1 END)::numeric / COUNT(*) * 100, 2) as levels_coverage,
            COUNT(CASE WHEN height IS NOT NULL
                        OR building_levels IS NOT NULL
                        OR min_height IS NOT NULL
                        OR building_levels_underground IS NOT NULL
                        OR ele IS NOT NULL
                   THEN 1 END) as "3Dbuildings_count",
            ROUND(AVG(area_sqm)::numeric, 2) as avg_area_all_sqm,
            ROUND(AVG(CASE WHEN height IS NOT NULL
                        OR building_levels IS NOT NULL
                        OR min_height IS NOT NULL
                        OR building_levels_underground IS NOT NULL
                        OR ele IS NOT NULL
                   THEN area_sqm END)::numeric, 2) as avg_area_3d_sqm
        FROM building_history
        {where_clause}
        GROUP BY {group_columns}
        ORDER BY total_buildings DESC
        """

        if self.debug:
            print(f"🔍 Analyzing 3D data coverage ({level})...")

        result = self.execute_query(query)

        if self.debug:
            unit = "cities" if level == "city" else "prefectures"
            print(f"✅ Found 3D data coverage for {len(result)} {unit}")

        return result

    def debug_area_calculation(self):
        """面積計算の詳細デバッグ"""
        query1 = """
        SELECT
            ST_GeometryType(way) as geom_type,
            COUNT(*) as count,
            ROUND(AVG(ST_Area(way))::numeric, 8) as avg_area_original,
            ROUND(AVG(ST_Area(ST_Transform(way, 6668)))::numeric, 8) as avg_area_transformed,
            ROUND(MIN(ST_Area(ST_Transform(way, 6668)))::numeric, 8) as min_area,
            ROUND(MAX(ST_Area(ST_Transform(way, 6668)))::numeric, 8) as max_area
        FROM
            planet_osm_polygon
        WHERE
            building IS NOT NULL AND building != ''
        GROUP BY
            ST_GeometryType(way)
        """

        query2 = """
        SELECT
            COUNT(*) as total_polygons,
            COUNT(*) FILTER (WHERE NOT ST_IsValid(way)) as invalid_polygons,
            COUNT(*) FILTER (WHERE ST_GeometryType(way) != 'ST_Polygon') as non_polygon_types
        FROM
            planet_osm_polygon
        WHERE
            building IS NOT NULL AND building != ''
        """

        print("\n=== Geometry Area Debug ===")
        print("Geometry Type Analysis:")
        result1 = self.execute_query(query1)
        print(result1.to_string())

        print("\nGeometry Validity Analysis:")
        result2 = self.execute_query(query2)
        print(result2.to_string())

        return result1, result2

    def get_editor_building_statistics(self) -> pd.DataFrame:
        """編集者ごとの建物編集統計を取得"""
        query = """
        SELECT
            e.uid,
            e.username,
            e.total_edits,
            e.building_edits,
            e.first_edit,
            e.last_edit,
            COUNT(DISTINCT bh.prefcode) as active_prefectures,
            COUNT(DISTINCT bh.building_type) as building_types,
            COUNT(CASE WHEN bh.height IS NOT NULL THEN 1 END) as height_edits,
            COUNT(CASE WHEN bh.building_levels IS NOT NULL THEN 1 END) as levels_edits,
            ROUND(COUNT(CASE WHEN bh.height IS NOT NULL THEN 1 END)::numeric /
                  NULLIF(e.building_edits, 0)::numeric * 100, 2) as height_edit_rate
        FROM editors e
        LEFT JOIN building_history bh ON e.uid = bh.uid
        WHERE e.building_edits > 0
        GROUP BY e.uid, e.username, e.total_edits, e.building_edits, e.first_edit, e.last_edit
        ORDER BY e.building_edits DESC
        """

        if self.debug:
            print("🔍 Getting editor building statistics...")

        result = self.execute_query(query)

        if self.debug:
            print(f"✅ Found statistics for {len(result)} building editors")

        return result

    def get_monthly_building_activity(self) -> pd.DataFrame:
        """月別の建物編集活動を分析"""
        query = """
        WITH monthly_edits AS (
            SELECT
                DATE_TRUNC('month', timestamp) as month,
                COUNT(*) as total_edits,
                COUNT(DISTINCT uid) as unique_editors,
                COUNT(DISTINCT prefcode) as active_prefectures,
                COUNT(CASE WHEN height IS NOT NULL THEN 1 END) as height_edits,
                COUNT(CASE WHEN building_levels IS NOT NULL THEN 1 END) as levels_edits,
                COUNT(DISTINCT building_type) as building_types
            FROM building_history
            GROUP BY DATE_TRUNC('month', timestamp)
            ORDER BY month
        )
        SELECT
            month,
            total_edits,
            unique_editors,
            active_prefectures,
            height_edits,
            levels_edits,
            building_types,
            LAG(total_edits) OVER (ORDER BY month) as prev_month_edits,
            CASE
                WHEN LAG(total_edits) OVER (ORDER BY month) > 0
                THEN ((total_edits - LAG(total_edits) OVER (ORDER BY month))::float /
                    LAG(total_edits) OVER (ORDER BY month) * 100)::numeric(10,2)
                ELSE NULL
            END as growth_rate_percent,
            ROUND(height_edits::numeric / total_edits::numeric * 100, 2) as height_coverage_percent
        FROM monthly_edits
        """

        if self.debug:
            print("🔍 Analyzing monthly building activity...")

        result = self.execute_query(query)

        if self.debug:
            print(f"✅ Analyzed activity for {len(result)} months")

        return result

    def get_yearly_building_activity(self) -> pd.DataFrame:
        """年別の建物編集活動を分析（厳密な年別アクティブ貢献者数を算出）

        月別の unique_editors を単純合計すると同一編集者が重複カウントされるため、
        年単位で GROUP BY して COUNT(DISTINCT uid) を直接集計する。
        """
        query = """
        WITH yearly_edits AS (
            SELECT
                DATE_TRUNC('year', timestamp) as year,
                COUNT(*) as total_edits,
                COUNT(DISTINCT uid) as unique_editors,
                COUNT(DISTINCT prefcode) as active_prefectures,
                COUNT(DISTINCT citycode) as active_cities,
                COUNT(CASE WHEN height IS NOT NULL THEN 1 END) as height_edits,
                COUNT(CASE WHEN building_levels IS NOT NULL THEN 1 END) as levels_edits,
                COUNT(DISTINCT building_type) as building_types,
                MIN(timestamp) as first_edit,
                MAX(timestamp) as last_edit
            FROM building_history
            GROUP BY DATE_TRUNC('year', timestamp)
        )
        SELECT
            EXTRACT(YEAR FROM year)::int as year,
            total_edits,
            unique_editors,
            active_prefectures,
            active_cities,
            height_edits,
            levels_edits,
            building_types,
            first_edit,
            last_edit,
            LAG(total_edits) OVER (ORDER BY year) as prev_year_edits,
            CASE
                WHEN LAG(total_edits) OVER (ORDER BY year) > 0
                THEN ((total_edits - LAG(total_edits) OVER (ORDER BY year))::float /
                    LAG(total_edits) OVER (ORDER BY year) * 100)::numeric(10,2)
                ELSE NULL
            END as growth_rate_percent,
            ROUND(height_edits::numeric / total_edits::numeric * 100, 2) as height_coverage_percent,
            ROUND(levels_edits::numeric / total_edits::numeric * 100, 2) as levels_coverage_percent
        FROM yearly_edits
        ORDER BY year
        """

        if self.debug:
            print("🔍 Analyzing yearly building activity...")

        result = self.execute_query(query)

        if self.debug:
            print(f"✅ Analyzed activity for {len(result)} years")

        return result

    def analyze_prefecture_building_patterns(self) -> pd.DataFrame:
        """都道府県別の建物データとその詳細を分析"""
        query = """
        WITH prefecture_data AS (
            SELECT
                prefcode,
                COUNT(*) AS "建物数",
                COUNT(DISTINCT building_type) AS "建物タイプ数",
                COUNT(DISTINCT uid) AS "編集者数",
                MIN(timestamp) AS first_edit,
                MAX(timestamp) AS last_edit
            FROM building_history
            GROUP BY prefcode
            ORDER BY "建物数" DESC
        )
        SELECT * FROM prefecture_data
        """

        if self.debug:
            print(
                "🔍 Analyzing prefecture building patterns with concentration metrics..."
            )

        try:
            # 基本的な都道府県データを取得
            prefecture_data = self.execute_query(query)

            if self.debug:
                print(f"✅ Retrieved basic data for {len(prefecture_data)} prefectures")

            if prefecture_data.empty:
                print("⚠️ No prefecture data found in the database")
                return pd.DataFrame()

            # 結果データを保持するリスト
            results = []

            # 各都道府県ごとの集中度指標を計算
            for idx, row in prefecture_data.iterrows():
                prefcode = row["prefcode"]
                building_count = row["建物数"]
                editor_count = row["編集者数"]
                first_edit = row["first_edit"]
                last_edit = row["last_edit"]

                # 各都道府県の編集者別貢献データを取得
                editors_query = f"""
                SELECT
                    uid,
                    username,
                    COUNT(*) as edit_count
                FROM building_history
                WHERE prefcode = '{prefcode}'
                GROUP BY uid, username
                ORDER BY edit_count DESC
                """

                try:
                    if self.debug and idx % 10 == 0:
                        print(
                            f"🔍 Processing prefecture {idx + 1}/{len(prefecture_data)}: {prefcode}"
                        )

                    editors_data = self.execute_query(editors_query)

                    if not editors_data.empty and editor_count > 0:
                        # 編集数の配列
                        edit_counts = editors_data["edit_count"].values

                        # トップ編集者の詳細
                        top_editor = editors_data.iloc[0]["username"]
                        top_editor_edits = editors_data.iloc[0]["edit_count"]
                        top_editor_share = top_editor_edits / building_count

                        # 上位5人の占有率
                        top5_count = min(5, len(editors_data))
                        top5_edits = editors_data.head(top5_count)["edit_count"].sum()
                        top5_share = top5_edits / building_count

                        # 上位10%の占有率
                        top10pct_count = max(1, int(len(editors_data) * 0.1))
                        top10pct_edits = editors_data.head(top10pct_count)[
                            "edit_count"
                        ].sum()
                        top10pct_share = top10pct_edits / building_count

                        # ジニ係数の計算
                        gini = calculate_gini(edit_counts)

                        # HHI（ハーフィンダール・ハーシュマン指数）の計算
                        shares = edit_counts / building_count
                        hhi = calculate_hhi(shares)

                        # 集中度評価
                        if gini < 0.4:
                            concentration = "低い集中"
                        elif gini < 0.6:
                            concentration = "中程度の集中"
                        elif gini < 0.8:
                            concentration = "高い集中"
                        else:
                            concentration = "非常に高い集中"

                        if self.debug and (idx + 1) % 10 == 0:
                            print(
                                f"  {prefcode}: ジニ係数 {gini:.3f}, トップ編集者: {top_editor} ({top_editor_share:.1%})"
                            )
                    else:
                        # データがない場合のデフォルト値
                        top_editor = "なし"
                        top_editor_share = 0
                        top5_share = 0
                        top10pct_share = 0
                        gini = 0
                        hhi = 0
                        concentration = "データなし"
                except Exception as e:
                    print(f"❌ Error processing {prefcode}: {str(e)}")
                    # エラーが発生した場合はデフォルト値を設定
                    top_editor = "エラー"
                    top_editor_share = 0
                    top5_share = 0
                    top10pct_share = 0
                    gini = 0
                    hhi = 0
                    concentration = "エラー"

                # 3Dデータの詳細を取得
                detail_query = f"""
                SELECT
                    COUNT(CASE WHEN height IS NOT NULL THEN 1 END) as height_count,
                    COUNT(CASE WHEN building_levels IS NOT NULL THEN 1 END) as levels_count,
                    COUNT(CASE WHEN min_height IS NOT NULL THEN 1 END) as min_height_count,
                    COUNT(CASE WHEN building_levels_underground IS NOT NULL THEN 1 END) as underground_count,
                    COUNT(CASE WHEN ele IS NOT NULL THEN 1 END) as ele_count,
                    COUNT(CASE WHEN start_date IS NOT NULL THEN 1 END) as date_count,
                    COUNT(CASE WHEN source IS NOT NULL THEN 1 END) as source_count,
                    COUNT(CASE WHEN name IS NOT NULL THEN 1 END) as name_count
                FROM building_history
                WHERE prefcode = '{prefcode}'
                """

                try:
                    detail_data = self.execute_query(detail_query)
                    if not detail_data.empty:
                        height_count = detail_data.iloc[0]["height_count"]
                        levels_count = detail_data.iloc[0]["levels_count"]
                        min_height_count = detail_data.iloc[0]["min_height_count"]
                        underground_count = detail_data.iloc[0]["underground_count"]
                        ele_count = detail_data.iloc[0]["ele_count"]
                        date_count = detail_data.iloc[0]["date_count"]
                        source_count = detail_data.iloc[0]["source_count"]
                        name_count = detail_data.iloc[0]["name_count"]

                        # カバレッジ率の計算
                        height_coverage = (
                            height_count / building_count * 100
                            if building_count > 0
                            else 0
                        )
                        levels_coverage = (
                            levels_count / building_count * 100
                            if building_count > 0
                            else 0
                        )
                    else:
                        height_count = levels_count = min_height_count = (
                            underground_count
                        ) = 0
                        ele_count = date_count = source_count = name_count = 0
                        height_coverage = levels_coverage = 0
                except Exception as e:
                    print(f"❌ Error getting details for {prefcode}: {str(e)}")
                    height_count = levels_count = min_height_count = (
                        underground_count
                    ) = 0
                    ele_count = date_count = source_count = name_count = 0
                    height_coverage = levels_coverage = 0

                # 日付の処理
                first_edit_str = (
                    first_edit.strftime("%Y-%m-%d") if first_edit is not None else "N/A"
                )
                last_edit_str = (
                    last_edit.strftime("%Y-%m-%d") if last_edit is not None else "N/A"
                )

                # 結果を追加
                results.append(
                    {
                        "都道府県コード": prefcode,
                        "建物数": building_count,
                        "編集者数": editor_count,
                        "ジニ係数": round(gini, 3),
                        "トップ編集者": top_editor,
                        "トップ編集者占有率": round(top_editor_share, 3),
                        "上位5人占有率": round(top5_share, 3),
                        "上位10%占有率": round(top10pct_share, 3),
                        "HHI": round(hhi, 3),
                        "height記述数": height_count,
                        "height記述率": round(height_coverage, 2),
                        "levels記述数": levels_count,
                        "levels記述率": round(levels_coverage, 2),
                        "min_height記述数": min_height_count,
                        "underground記述数": underground_count,
                        "ele記述数": ele_count,
                        "start_date記述数": date_count,
                        "source記述数": source_count,
                        "name記述数": name_count,
                        "編集開始日": first_edit_str,
                        "最終編集日": last_edit_str,
                        "集中度評価": concentration,
                    }
                )

            # データフレームに変換
            result_df = pd.DataFrame(results)

            if self.debug:
                print(f"✅ Calculated metrics for {len(result_df)} prefectures")

            return result_df

        except Exception as e:
            print(f"❌ Error analyzing prefecture activity: {str(e)}")
            import traceback

            traceback.print_exc()
            return pd.DataFrame()  # 空のデータフレームを返す

    def generate_reports(self, output_prefix: str = "building_analysis"):
        """分析レポートの生成"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = "reports"

        # 出力ディレクトリの作成
        os.makedirs(output_dir, exist_ok=True)

        print("\n=== Debug Area Calculation ===")
        self.debug_area_calculation()

        print(f"\n=== Generating Building Analysis Reports ===")
        print(f"Timestamp: {timestamp}")
        print(f"Output directory: {output_dir}")
        print(f"Output prefix: {output_prefix}")

        try:
            # データベース構造の確認
            if not self.check_tables_exist():
                print(
                    "\n❌ Required tables are missing. Please check the database schema."
                )
                return False

            # 1. 建物統計
            print("\n🔍 Analyzing building statistics...")
            building_stats = self.get_building_statistics()
            output_file = f"{output_dir}/{output_prefix}_building_stats_{timestamp}.csv"
            building_stats.to_csv(output_file, index=False)
            print(f"✅ Saved to {output_file}")

            # 2. 建物タイプ統計
            print("\n🔍 Analyzing building type statistics...")
            building_type_stats = self.get_building_type_statistics()
            output_file = (
                f"{output_dir}/{output_prefix}_building_type_stats_{timestamp}.csv"
            )
            building_type_stats.to_csv(output_file, index=False)
            print(f"✅ Saved to {output_file}")

            # 3. 3Dデータカバレッジ
            print("\n🔍 Analyzing 3D data coverage (prefecture)...")
            coverage_stats_pref = self.get_3d_data_coverage(level="prefecture")
            output_file = (
                f"{output_dir}/{output_prefix}_3d_coverage_prefecture_{timestamp}.csv"
            )
            coverage_stats_pref.to_csv(output_file, index=False)
            print(f"✅ Saved to {output_file}")

            print("\n🔍 Analyzing 3D data coverage (city)...")
            coverage_stats_city = self.get_3d_data_coverage(level="city")
            output_file = (
                f"{output_dir}/{output_prefix}_3d_coverage_city_{timestamp}.csv"
            )
            coverage_stats_city.to_csv(output_file, index=False)
            print(f"✅ Saved to {output_file}")

            # 4. 編集者統計
            print("\n🔍 Analyzing editor statistics...")
            editor_stats = self.get_editor_building_statistics()
            output_file = f"{output_dir}/{output_prefix}_editor_stats_{timestamp}.csv"
            editor_stats.to_csv(output_file, index=False)
            print(f"✅ Saved to {output_file}")

            # 5. 建物面積分析
            print("\n🔍 Analyzing building area statistics...")
            area_stats = self.get_building_area_analysis()
            output_file = f"{output_dir}/{output_prefix}_area_stats_{timestamp}.csv"
            area_stats.to_csv(output_file, index=False)
            print(f"✅ Saved to {output_file}")

            # 6. 月別活動分析
            print("\n🔍 Analyzing monthly activity...")
            monthly_activity = self.get_monthly_building_activity()
            output_file = (
                f"{output_dir}/{output_prefix}_monthly_activity_{timestamp}.csv"
            )
            monthly_activity.to_csv(output_file, index=False)
            print(f"✅ Saved to {output_file}")

            # 6-2. 年別活動分析（厳密な年別アクティブ貢献者数）
            print("\n🔍 Analyzing yearly activity...")
            yearly_activity = self.get_yearly_building_activity()
            output_file = (
                f"{output_dir}/{output_prefix}_yearly_activity_{timestamp}.csv"
            )
            yearly_activity.to_csv(output_file, index=False)
            print(f"✅ Saved to {output_file}")

            # 7. 都道府県別建物分析
            print("\n🔍 Analyzing prefecture building patterns...")
            prefecture_analysis = self.analyze_prefecture_building_patterns()
            output_file = (
                f"{output_dir}/{output_prefix}_prefecture_analysis_{timestamp}.csv"
            )
            prefecture_analysis.to_csv(output_file, index=False, encoding="utf-8-sig")
            print(f"✅ Saved to {output_file}")

            # サマリー情報の表示
            print("\n=== Analysis Summary ===")

            if not building_stats.empty:
                total_buildings = building_stats["building_count"].sum()
                total_height = building_stats["height_count"].sum()
                total_levels = building_stats["levels_count"].sum()
                avg_area = building_stats["avg_building_area_ha"].mean()
                total_area = building_stats["total_building_area_ha"].sum()

                print(f"\nBuilding Statistics:")
                print(f"Total buildings: {total_buildings:,}")
                print(
                    f"Buildings with height data: {total_height:,} ({total_height / total_buildings * 100:.1f}%)"
                )
                print(
                    f"Buildings with levels data: {total_levels:,} ({total_levels / total_buildings * 100:.1f}%)"
                )
                print(f"Average building area: {avg_area:.4f} ha")
                print(f"Total building footprint area: {total_area:.4f} ha")

                print("\nTop 5 building types:")
                top5 = (
                    building_stats.groupby("building_types")
                    .agg(
                        {
                            "building_count": "sum",
                            "avg_height": "mean",
                            "avg_levels": "mean",
                            "avg_building_area_ha": "mean",
                        }
                    )
                    .nlargest(5, "building_count")
                )
                print(top5.to_string())

            if not prefecture_analysis.empty:
                print("\n=== Prefecture Analysis Summary ===")
                print(f"Total prefectures analyzed: {len(prefecture_analysis)}")

                # 集中度評価の分布
                if "集中度評価" in prefecture_analysis.columns:
                    concentration_dist = prefecture_analysis[
                        "集中度評価"
                    ].value_counts()
                    print("\nConcentration Rating Distribution:")
                    for rating, count in concentration_dist.items():
                        print(f"  {rating}: {count}")

                # height記述率の高い上位5都道府県
                if "height記述率" in prefecture_analysis.columns:
                    print("\nTop 5 Prefectures by Height Data Coverage:")
                    top_height = prefecture_analysis.nlargest(5, "height記述率")
                    display_cols = [
                        "都道府県コード",
                        "建物数",
                        "height記述数",
                        "height記述率",
                    ]
                    print(top_height[display_cols].to_string(index=False))

                # 平均面積が大きい上位5都道府県
                print("\nTop 5 Prefectures by Building Area:")
                largest_area_query = """
                SELECT
                    prefcode,
                    COUNT(*) as building_count,
                    ROUND(AVG(area_sqm)::numeric, 2) as avg_area_sqm,
                    ROUND(MAX(area_sqm)::numeric, 2) as max_area_sqm
                FROM building_history
                GROUP BY prefcode
                ORDER BY avg_area_sqm DESC
                LIMIT 5;
                """
                largest_area = self.execute_query(largest_area_query)
                if not largest_area.empty:
                    print(largest_area.to_string(index=False))

            if not monthly_activity.empty:
                print("\nMonthly Activity Summary:")
                latest_month = monthly_activity.iloc[-1]
                print(f"Latest month: {latest_month['month'].strftime('%Y-%m')}")
                print(f"Total edits: {latest_month['total_edits']:,}")
                print(f"Unique editors: {latest_month['unique_editors']:,}")
                print(
                    f"Height data coverage: {latest_month['height_coverage_percent']:.1f}%"
                )

                # 成長率の計算
                if not pd.isna(latest_month["growth_rate_percent"]):
                    growth = latest_month["growth_rate_percent"]
                    trend = "⬆️" if growth > 0 else "⬇️" if growth < 0 else "➡️"
                    print(f"Monthly growth rate: {trend} {abs(growth):.1f}%")

            if not yearly_activity.empty:
                print("\nYearly Activity Summary (厳密な年別アクティブ貢献者数):")
                for _, yr in yearly_activity.iterrows():
                    growth_str = ""
                    if not pd.isna(yr["growth_rate_percent"]):
                        growth = yr["growth_rate_percent"]
                        trend = "⬆️" if growth > 0 else "⬇️" if growth < 0 else "➡️"
                        growth_str = f", growth {trend} {abs(growth):.1f}%"
                    print(
                        f"  {yr['year']}: edits {yr['total_edits']:,}, "
                        f"unique editors {yr['unique_editors']:,}, "
                        f"height coverage {yr['height_coverage_percent']:.1f}%"
                        f"{growth_str}"
                    )

            return True

        except Exception as e:
            print(f"\n❌ Error during report generation: {str(e)}")
            import traceback

            traceback.print_exc()
            return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OSM建物データの3D分析")
    parser.add_argument(
        "--dbname", type=str, default="osm_3ddata_analysis", help="データベース名"
    )
    parser.add_argument(
        "--user", type=str, default="postgres", help="データベースユーザー"
    )
    parser.add_argument(
        "--password", type=str, default="", help="データベースパスワード"
    )
    parser.add_argument(
        "--host", type=str, default="localhost", help="データベースホスト"
    )
    parser.add_argument("--port", type=str, default="5432", help="データベースポート")
    parser.add_argument("--debug", action="store_true", help="デバッグモードの有効化")
    parser.add_argument(
        "--prefix", type=str, default="building_analysis", help="出力ファイルの接頭辞"
    )

    args = parser.parse_args()

    # 開始時間を記録
    start_time = datetime.now()
    print(f"開始時間: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

    config = DBConfig(
        dbname=args.dbname,
        user=args.user,
        password=args.password,
        host=args.host,
        port=args.port,
    )

    analyzer = BuildingDataAnalyzer(config, debug=args.debug)
    success = analyzer.generate_reports(args.prefix)

    if success:
        print("\n✅ Analysis completed successfully.")
    else:
        print("\n❌ Analysis failed. Check logs for details.")

    # 処理時間を計算
    end_time = datetime.now()
    processing_time = end_time - start_time
    print(f"\n処理時間: {processing_time.total_seconds():.2f}秒")

    analyzer.close()
