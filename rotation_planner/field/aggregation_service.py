"""
集計サービス層 - Repository + spatial.py + aggregation.py を組み合わせた集計サービス

Usage:
    from rotation_planner.field.aggregation_service import (
        get_cross_tabulation_for_user,
        copy_crop_polygons_to_next_year,
        get_subsidy_summary,
        export_cross_tabulation_csv,
        build_land_breakdown_for_crop,
    )
"""

import csv
import datetime
import io
import logging
from typing import List, Dict, Tuple, Union

import pandas as pd

from rotation_planner.common.db_access import PaddyPolygonRepository, CropPolygonRepository
from rotation_planner.common.models import LandCategory
from rotation_planner.field.spatial import split_crop_by_land_category
from rotation_planner.field.aggregation import (
    CropLandBreakdown, aggregate_by_crop, build_cross_tabulation,
    format_cross_table_for_display,
)

logger = logging.getLogger(__name__)


# =============================================================================
# build_land_breakdown_for_crop
# =============================================================================

def build_land_breakdown_for_crop(
    crop_polygon: dict,
    paddy_polygons: list
) -> CropLandBreakdown:
    """
    1件の作付けポリゴンの地目内訳を計算。

    Args:
        crop_polygon: dict (crop_name, field_id, year, geometry, ...)
        paddy_polygons: list of dict (geometry, is_converted, conversion_start_year, ...)

    Returns:
        CropLandBreakdown
    """
    crop_name = crop_polygon['crop_name']
    field_id = crop_polygon['field_id']
    year = crop_polygon['year']
    crop_geom_str = crop_polygon['geometry']

    split_result = split_crop_by_land_category(crop_geom_str, paddy_polygons)

    field_area_ha = 0.0
    converted_areas: Dict[Union[int, str], float] = {}
    paddy_area_ha = 0.0

    for item in split_result:
        category = item['land_category']
        area_ha = item['area_ha']
        conversion_year = item.get('conversion_start_year')

        if category == LandCategory.FIELD:
            field_area_ha += area_ha
        elif category == LandCategory.CONVERTED:
            year_key = conversion_year if conversion_year is not None else 'unknown'
            converted_areas[year_key] = converted_areas.get(year_key, 0.0) + area_ha
        elif category == LandCategory.PADDY:
            paddy_area_ha += area_ha

    total_area_ha = field_area_ha + sum(converted_areas.values()) + paddy_area_ha

    return CropLandBreakdown(
        crop_name=crop_name,
        field_id=field_id,
        year=year,
        field_area_ha=field_area_ha,
        converted_areas=converted_areas,
        paddy_area_ha=paddy_area_ha,
        total_area_ha=total_area_ha,
    )


# =============================================================================
# get_cross_tabulation_for_user
# =============================================================================

def get_cross_tabulation_for_user(
    user_id: int, year: int
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    指定ユーザー・年度のクロス集計表を生成。

    Returns:
        (raw_df, display_df)
        - raw_df: 数値DataFrame（計算用）
        - display_df: 表示用DataFrame（0.0→'-'、小数2桁）
    """
    crop_polygons = CropPolygonRepository.get_all_for_user_year(user_id, year)
    paddy_polygons = PaddyPolygonRepository.get_all_for_user(user_id)

    breakdowns: List[CropLandBreakdown] = []
    for crop_poly in crop_polygons:
        breakdown = build_land_breakdown_for_crop(crop_poly, paddy_polygons)
        breakdowns.append(breakdown)

    agg_rows = aggregate_by_crop(breakdowns)
    raw_df = build_cross_tabulation(agg_rows)
    display_df = format_cross_table_for_display(raw_df)

    return raw_df, display_df


# =============================================================================
# copy_crop_polygons_to_next_year
# =============================================================================

def copy_crop_polygons_to_next_year(user_id: int, from_year: int, to_year: int) -> Tuple[int, str]:
    """
    前年度の作付けポリゴンを次年度にコピー。

    Returns:
        (コピー件数, メッセージ文字列)
    """
    count = CropPolygonRepository.copy_from_previous_year(user_id, from_year, to_year)

    if count > 0:
        message = f"{from_year}年度の作付けポリゴン{count}件を{to_year}年度にコピーしました"
    else:
        message = f"{from_year}年度に作付けポリゴンが存在しないため、コピーできませんでした"

    logger.info(f"copy_crop_polygons_to_next_year: user_id={user_id}, {from_year}→{to_year}, count={count}")

    return count, message


# =============================================================================
# get_subsidy_summary
# =============================================================================

def get_subsidy_summary(user_id: int) -> List[Dict]:
    """
    畑地化補助金の残り年数サマリを取得。

    Returns:
        [{'field_id': int, 'area_ha': float, 'start_year': int|None,
          'remaining_years': int|None}, ...]
    """
    all_polygons = PaddyPolygonRepository.get_all_for_user(user_id)
    current_year = datetime.date.today().year

    summary = []
    for poly in all_polygons:
        if not poly.get('is_converted'):
            continue

        start_year = poly.get('conversion_start_year')
        if start_year is not None:
            elapsed = current_year - start_year
            remaining = max(0, 5 - elapsed)
        else:
            remaining = None

        summary.append({
            'field_id': poly['field_id'],
            'area_ha': poly['area_ha'],
            'start_year': start_year,
            'remaining_years': remaining,
        })

    return summary


# =============================================================================
# export_cross_tabulation_csv
# =============================================================================

def export_cross_tabulation_csv(user_id: int, year: int) -> str:
    """
    クロス集計表をCSV文字列として出力（UTF-8 BOM付き）。
    """
    raw_df, display_df = get_cross_tabulation_for_user(user_id, year)

    output = io.StringIO()
    output.write('\ufeff')  # BOM

    writer = csv.writer(output)
    writer.writerow(display_df.columns.tolist())
    for _, row in display_df.iterrows():
        writer.writerow(row.tolist())

    csv_str = output.getvalue()
    output.close()

    logger.info(
        f"export_cross_tabulation_csv: user_id={user_id}, year={year}, rows={len(display_df)}"
    )

    return csv_str
