"""
rotation_planner.field.paddy_crud - 水田ポリゴンCRUD操作モジュール

水田ポリゴンの登録・削除・更新・一括インポートを提供。
user_idによるマルチテナント分離を保証。

Usage:
    from rotation_planner.field.paddy_crud import (
        get_paddy_polygons_df,
        register_paddy_polygon,
        delete_paddy_polygon,
        update_paddy_conversion,
        import_paddy_from_kml,
    )
"""

import json
import pandas as pd
from typing import Tuple, Optional, Any

# DB関連
from rotation_planner.common.db_access import PaddyPolygonRepository, FieldRepository
from rotation_planner.common import (
    format_success,
    format_error,
    format_warning,
)

# 空間処理
from rotation_planner.field.spatial import calculate_geodesic_area_ha, geojson_to_shapely

# KMLパーサー
from rotation_planner.field.kml_parser import parse_kml_or_kmz_bytes

# 既存のヘルパー関数を再利用
from rotation_planner.field.crud import get_user_id_from_state


# =============================================================================
# 水田ポリゴンCRUD関数
# =============================================================================

def get_paddy_polygons_df(state: dict, field_id: Optional[int] = None) -> pd.DataFrame:
    """
    水田ポリゴン一覧をDataFrameで返す

    Args:
        state: ユーザー状態
        field_id: ほ場ID（指定時はそのほ場のみ、未指定時はユーザー全体）

    Returns:
        水田ポリゴン一覧のDataFrame
        カラム: ['ID', 'ほ場ID', '面積(ha)', '地目', '畑地化開始年', 'ソース']
    """
    user_id = get_user_id_from_state(state)
    if not user_id:
        return pd.DataFrame(columns=['ID', 'ほ場ID', '面積(ha)', '地目', '畑地化開始年', 'ソース'])

    # データ取得
    if field_id:
        polygons = PaddyPolygonRepository.get_by_field(field_id)
    else:
        polygons = PaddyPolygonRepository.get_all_for_user(user_id)

    if not polygons:
        return pd.DataFrame(columns=['ID', 'ほ場ID', '面積(ha)', '地目', '畑地化開始年', 'ソース'])

    # DataFrame変換
    rows = []
    for p in polygons:
        land_category = '畑地化済' if p.get('is_converted') else '水田'
        rows.append({
            'ID': p.get('id'),
            'ほ場ID': p.get('field_id'),
            '面積(ha)': f"{p.get('area_ha', 0):.4f}",
            '地目': land_category,
            '畑地化開始年': p.get('conversion_start_year') or '',
            'ソース': p.get('source', 'manual'),
        })

    return pd.DataFrame(rows)


def register_paddy_polygon(
    state: dict,
    field_id: int,
    geometry_text: str,
    is_converted: bool,
    conversion_start_year: Optional[int],
    source: str,
    notes: str
) -> Tuple[pd.DataFrame, str]:
    """
    水田ポリゴン登録

    Args:
        state: ユーザー状態
        field_id: ほ場ID
        geometry_text: GeoJSON文字列
        is_converted: 畑地化フラグ
        conversion_start_year: 畑地化開始年度
        source: データソース（'manual', 'maff', 'kml'）
        notes: 備考

    Returns:
        (更新後のDataFrame, メッセージ)
    """
    user_id = get_user_id_from_state(state)
    if not user_id:
        return pd.DataFrame(), format_error("ログインしてください")

    # ほ場が存在するか確認
    field = FieldRepository.get_field_by_id(field_id)
    if not field:
        return get_paddy_polygons_df(state), format_error(f"ほ場ID {field_id} が見つかりません")

    # ユーザーの所有確認
    if field.get("user_id") != user_id:
        return get_paddy_polygons_df(state), format_error("このほ場にアクセスする権限がありません")

    # GeoJSON解析
    try:
        polygon = geojson_to_shapely(geometry_text)
    except Exception as e:
        return get_paddy_polygons_df(state), format_error(f"ジオメトリの解析に失敗しました: {e}")

    # 面積計算
    try:
        area_ha = calculate_geodesic_area_ha(polygon)
    except Exception as e:
        return get_paddy_polygons_df(state), format_error(f"面積計算に失敗しました: {e}")

    # 登録
    try:
        polygon_id = PaddyPolygonRepository.create(
            field_id=field_id,
            geometry=geometry_text,
            area_ha=area_ha,
            is_converted=is_converted,
            conversion_start_year=conversion_start_year,
            source=source,
            notes=notes or None
        )
        message = format_success(f"水田ポリゴンを登録しました（ID: {polygon_id}, 面積: {area_ha:.4f} ha）")
        return get_paddy_polygons_df(state), message
    except Exception as e:
        return get_paddy_polygons_df(state), format_error(f"登録に失敗しました: {e}")


def delete_paddy_polygon(state: dict, polygon_id: int) -> Tuple[pd.DataFrame, str]:
    """
    水田ポリゴン削除

    Args:
        state: ユーザー状態
        polygon_id: ポリゴンID

    Returns:
        (更新後のDataFrame, メッセージ)
    """
    user_id = get_user_id_from_state(state)
    if not user_id:
        return pd.DataFrame(), format_error("ログインしてください")

    # ポリゴンが存在するか確認
    polygon = PaddyPolygonRepository.get_by_id(polygon_id)
    if not polygon:
        return get_paddy_polygons_df(state), format_warning(f"水田ポリゴン（ID: {polygon_id}）が見つかりません")

    # ほ場の所有確認
    field_id = polygon.get("field_id")
    field = FieldRepository.get_field_by_id(field_id)
    if not field or field.get("user_id") != user_id:
        return get_paddy_polygons_df(state), format_error("このポリゴンを削除する権限がありません")

    try:
        success = PaddyPolygonRepository.delete(polygon_id)
        if success:
            message = format_success(f"水田ポリゴン（ID: {polygon_id}）を削除しました")
        else:
            message = format_error(f"削除に失敗しました")
        return get_paddy_polygons_df(state), message
    except Exception as e:
        return get_paddy_polygons_df(state), format_error(f"削除に失敗しました: {e}")


def update_paddy_conversion(
    state: dict,
    polygon_id: int,
    is_converted: bool,
    conversion_start_year: Optional[int]
) -> Tuple[pd.DataFrame, str]:
    """
    畑地化フラグと開始年度の更新

    Args:
        state: ユーザー状態
        polygon_id: ポリゴンID
        is_converted: 畑地化フラグ
        conversion_start_year: 畑地化開始年度

    Returns:
        (更新後のDataFrame, メッセージ)
    """
    user_id = get_user_id_from_state(state)
    if not user_id:
        return pd.DataFrame(), format_error("ログインしてください")

    # ポリゴンが存在するか確認
    polygon = PaddyPolygonRepository.get_by_id(polygon_id)
    if not polygon:
        return get_paddy_polygons_df(state), format_warning(f"水田ポリゴン（ID: {polygon_id}）が見つかりません")

    # ほ場の所有確認
    field_id = polygon.get("field_id")
    field = FieldRepository.get_field_by_id(field_id)
    if not field or field.get("user_id") != user_id:
        return get_paddy_polygons_df(state), format_error("このポリゴンを更新する権限がありません")

    try:
        success = PaddyPolygonRepository.update(
            polygon_id,
            is_converted=is_converted,
            conversion_start_year=conversion_start_year
        )
        if success:
            status = '畑地化済' if is_converted else '水田'
            message = format_success(f"水田ポリゴン（ID: {polygon_id}）を更新しました（地目: {status}）")
        else:
            message = format_error(f"更新に失敗しました")
        return get_paddy_polygons_df(state), message
    except Exception as e:
        return get_paddy_polygons_df(state), format_error(f"更新に失敗しました: {e}")


def import_paddy_from_kml(
    state: dict,
    file,
    field_id: int,
    is_converted: bool,
    conversion_start_year: Optional[int]
) -> Tuple[pd.DataFrame, str]:
    """
    KML/KMZファイルから水田ポリゴンを一括インポート

    Args:
        state: ユーザー状態
        file: Gradioアップロードファイル（.name と .read() メソッドを持つ）
        field_id: ほ場ID
        is_converted: 畑地化フラグ
        conversion_start_year: 畑地化開始年度

    Returns:
        (更新後のDataFrame, メッセージ)
    """
    user_id = get_user_id_from_state(state)
    if not user_id:
        return pd.DataFrame(), format_error("ログインしてください")

    # ほ場が存在するか確認
    field = FieldRepository.get_field_by_id(field_id)
    if not field:
        return get_paddy_polygons_df(state), format_error(f"ほ場ID {field_id} が見つかりません")

    # ユーザーの所有確認
    if field.get("user_id") != user_id:
        return get_paddy_polygons_df(state), format_error("このほ場にアクセスする権限がありません")

    # ファイル読み込み
    try:
        file_bytes = file.read()
        filename = file.name
    except Exception as e:
        return get_paddy_polygons_df(state), format_error(f"ファイル読み込みに失敗しました: {e}")

    # KMLパース
    try:
        parsed_fields = parse_kml_or_kmz_bytes(file_bytes, filename)
    except Exception as e:
        return get_paddy_polygons_df(state), format_error(f"KML/KMZの解析に失敗しました: {e}")

    if not parsed_fields:
        return get_paddy_polygons_df(state), format_error("ポリゴンが見つかりませんでした")

    # 各ポリゴンを登録
    count = 0
    errors = []

    for field_data in parsed_fields:
        try:
            # 座標を GeoJSON に変換
            # KMLパーサーが返す座標は [[lat, lng], ...] 形式
            # GeoJSONは [[[lng, lat], ...]] 形式なので変換が必要
            coords_latlng = field_data.get('coordinates', [])
            if not coords_latlng or len(coords_latlng) < 3:
                continue

            # [lat, lng] → [lng, lat] に変換
            coords_lnglat = [[coord[1], coord[0]] for coord in coords_latlng]

            # ポリゴンを閉じる（最初と最後が同じでなければ）
            if coords_lnglat[0] != coords_lnglat[-1]:
                coords_lnglat.append(coords_lnglat[0])

            geojson_obj = {
                "type": "Polygon",
                "coordinates": [coords_lnglat]
            }
            geometry_text = json.dumps(geojson_obj)

            # 面積計算
            polygon = geojson_to_shapely(geometry_text)
            area_ha = calculate_geodesic_area_ha(polygon)

            # 登録
            PaddyPolygonRepository.create(
                field_id=field_id,
                geometry=geometry_text,
                area_ha=area_ha,
                is_converted=is_converted,
                conversion_start_year=conversion_start_year,
                source='kml',
                notes=field_data.get('name')
            )
            count += 1

        except Exception as e:
            errors.append(f"{field_data.get('name', '不明')}: {str(e)}")

    # 結果メッセージ
    if count > 0:
        message = format_success(f"{count}件の水田ポリゴンを登録しました")
        if errors:
            message += f"\n（{len(errors)}件のエラーがありました）"
    else:
        message = format_error("ポリゴンの登録に失敗しました")

    return get_paddy_polygons_df(state), message
