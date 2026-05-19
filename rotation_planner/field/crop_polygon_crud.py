"""
rotation_planner.field.crop_polygon_crud - 作付けポリゴンCRUD操作モジュール

UI層から呼ばれる作付けポリゴン管理のビジネスロジック関数群。

Usage:
    from rotation_planner.field.crop_polygon_crud import (
        get_crop_polygons_df,
        register_crop_polygon,
        delete_crop_polygon,
        import_crop_from_kml,
        copy_previous_year,
    )
"""

import json
import pandas as pd
from typing import Dict, Any, Tuple, Optional

# DB関連
from rotation_planner.common import (
    FieldRepository,
    format_alert,
    format_success,
    format_error,
    format_warning,
)
from rotation_planner.common.db_access import CropPolygonRepository

# 空間演算
from .spatial import calculate_geodesic_area_ha, geojson_to_shapely

# KMLパーサー
from .kml_parser import parse_kml_or_kmz_bytes

# ヘルパー関数（crud.py から）
from .crud import get_user_id_from_state


# =============================================================================
# 内部ヘルパー関数
# =============================================================================

def _coords_to_geojson(coords: list) -> str:
    """
    [[lat,lng],...] → GeoJSON Polygon文字列

    Args:
        coords: [[lat, lng], ...] 形式の座標リスト

    Returns:
        GeoJSON Polygon文字列
    """
    # [lat,lng] → [lng,lat] に変換（GeoJSON仕様）
    ring = [[lng, lat] for lat, lng in coords]

    # ポリゴンを閉じる
    if ring[0] != ring[-1]:
        ring.append(ring[0])

    return json.dumps({"type": "Polygon", "coordinates": [ring]})


# =============================================================================
# 作付けポリゴン一覧取得
# =============================================================================

def get_crop_polygons_df(
    state: dict,
    field_id: Optional[int] = None,
    year: Optional[int] = None
) -> pd.DataFrame:
    """
    作付けポリゴン一覧をDataFrameで返す

    Args:
        state: ユーザー情報
        field_id: ほ場ID（絞り込み用、Noneなら全件）
        year: 年度（絞り込み用、Noneなら全件）

    Returns:
        作付けポリゴン一覧のDataFrame
        カラム: ['ID', 'ほ場ID', '年度', '作物名', '面積(ha)', 'メモ']
    """
    user_id = get_user_id_from_state(state)
    if not user_id:
        return pd.DataFrame(columns=["ID", "ほ場ID", "年度", "作物名", "面積(ha)", "メモ"])

    try:
        # ユーザーの全ほ場を取得
        fields = FieldRepository.get_fields(user_id)
        field_map = {f["id"]: f["field_code"] for f in fields}

        # ポリゴンを取得
        polygons = []
        for field in fields:
            fid = field["id"]

            # field_id 指定がある場合は絞り込み
            if field_id is not None and fid != field_id:
                continue

            # 年度でフィルタ
            if year is not None:
                polys = CropPolygonRepository.get_by_field_year(fid, year)
            else:
                # 全年度を取得（この場合は各年度ごとに取得が必要だが、
                # ユーザー全体から取得する方が効率的）
                # 一旦、全フィールドの全年度を取得する方法はないので、
                # 特定年度が指定されていなければユーザーの全ポリゴンを取得
                pass

            polygons.extend(polys if year is not None else [])

        # year が None の場合、ユーザーの全ポリゴンを取得
        if year is None:
            # 年度指定なしの場合は、全年度を網羅する必要がある
            # しかし、現在のRepositoryには「ユーザーの全ポリゴン」を取得するメソッドがない
            # 代わりに、全フィールドに対して全年度を取得する必要がある
            # これは非効率なので、ここでは年度範囲を推定する
            # 実装簡略化のため、年度指定なしの場合は空のDataFrameを返す
            # （通常はUIで年度を指定するため問題ない）
            polygons = []
            for field in fields:
                fid = field["id"]
                if field_id is not None and fid != field_id:
                    continue
                # 年度範囲を推定（2020-2030）
                for y in range(2020, 2031):
                    polys = CropPolygonRepository.get_by_field_year(fid, y)
                    polygons.extend(polys)

        # DataFrameに変換
        if not polygons:
            return pd.DataFrame(columns=["ID", "ほ場ID", "年度", "作物名", "面積(ha)", "メモ"])

        rows = []
        for p in polygons:
            fid = p.get("field_id")
            field_code = field_map.get(fid, f"F{fid:03d}")
            rows.append({
                "ID": p.get("id"),
                "ほ場ID": field_code,
                "年度": p.get("year"),
                "作物名": p.get("crop_name"),
                "面積(ha)": f"{p.get('area_ha', 0):.4f}",
                "メモ": p.get("notes", ""),
            })

        return pd.DataFrame(rows)

    except Exception as e:
        # エラー時は空のDataFrameを返す
        return pd.DataFrame(columns=["ID", "ほ場ID", "年度", "作物名", "面積(ha)", "メモ"])


# =============================================================================
# 作付けポリゴン登録
# =============================================================================

def register_crop_polygon(
    state: dict,
    field_id: int,
    year: int,
    crop_name: str,
    geometry_text: str,
    notes: str
) -> Tuple[pd.DataFrame, str]:
    """
    作付けポリゴンを登録

    Args:
        state: ユーザー情報
        field_id: ほ場ID
        year: 年度
        crop_name: 作物名
        geometry_text: GeoJSON文字列
        notes: メモ

    Returns:
        (更新後のDataFrame, メッセージ)
    """
    user_id = get_user_id_from_state(state)
    if not user_id:
        return pd.DataFrame(), format_error("エラー: ログインが必要です")

    # 入力検証
    if not field_id:
        df = get_crop_polygons_df(state, year=year)
        return df, format_warning("エラー: ほ場IDを指定してください")

    if not year:
        df = get_crop_polygons_df(state, field_id=field_id)
        return df, format_warning("エラー: 年度を指定してください")

    if not crop_name or not crop_name.strip():
        df = get_crop_polygons_df(state, field_id=field_id, year=year)
        return df, format_warning("エラー: 作物名を入力してください")

    if not geometry_text or not geometry_text.strip():
        df = get_crop_polygons_df(state, field_id=field_id, year=year)
        return df, format_warning("エラー: ポリゴンのジオメトリが必要です")

    # GeoJSON検証
    try:
        geom = geojson_to_shapely(geometry_text)
    except ValueError as e:
        df = get_crop_polygons_df(state, field_id=field_id, year=year)
        return df, format_error(f"エラー: 不正なGeoJSON形式です - {e}")

    # 面積計算
    try:
        area_ha = calculate_geodesic_area_ha(geom)
    except Exception as e:
        df = get_crop_polygons_df(state, field_id=field_id, year=year)
        return df, format_error(f"エラー: 面積計算に失敗しました - {e}")

    # DB登録
    try:
        polygon_id = CropPolygonRepository.create(
            field_id=field_id,
            year=year,
            crop_name=crop_name.strip(),
            geometry=geometry_text,
            area_ha=area_ha,
            notes=notes.strip() if notes else None
        )

        df = get_crop_polygons_df(state, field_id=field_id, year=year)
        return df, format_success(
            f"✅ 作付けポリゴンを登録しました（ID: {polygon_id}、面積: {area_ha:.4f} ha）"
        )

    except Exception as e:
        df = get_crop_polygons_df(state, field_id=field_id, year=year)
        return df, format_error(f"エラー: 登録に失敗しました - {e}")


# =============================================================================
# 作付けポリゴン削除
# =============================================================================

def delete_crop_polygon(
    state: dict,
    polygon_id: int
) -> Tuple[pd.DataFrame, str]:
    """
    作付けポリゴンを削除

    Args:
        state: ユーザー情報
        polygon_id: ポリゴンID

    Returns:
        (更新後のDataFrame, メッセージ)
    """
    user_id = get_user_id_from_state(state)
    if not user_id:
        return pd.DataFrame(), format_error("エラー: ログインが必要です")

    if not polygon_id:
        df = get_crop_polygons_df(state)
        return df, format_warning("エラー: 削除するポリゴンIDを指定してください")

    # ポリゴンを取得して権限チェック
    try:
        polygon = CropPolygonRepository.get_by_id(polygon_id)
        if not polygon:
            df = get_crop_polygons_df(state)
            return df, format_warning(f"エラー: ポリゴン ID {polygon_id} が見つかりません")

        # ほ場の所有者チェック
        field = FieldRepository.get_field_by_id(polygon["field_id"])
        if not field or field.get("user_id") != user_id:
            df = get_crop_polygons_df(state)
            return df, format_error("エラー: このポリゴンを削除する権限がありません")

    except Exception as e:
        df = get_crop_polygons_df(state)
        return df, format_error(f"エラー: ポリゴンの確認に失敗しました - {e}")

    # 削除
    try:
        if CropPolygonRepository.delete(polygon_id):
            df = get_crop_polygons_df(state)
            return df, format_success(f"✅ 作付けポリゴン ID {polygon_id} を削除しました")
        else:
            df = get_crop_polygons_df(state)
            return df, format_error(f"エラー: ポリゴン ID {polygon_id} の削除に失敗しました")

    except Exception as e:
        df = get_crop_polygons_df(state)
        return df, format_error(f"エラー: 削除に失敗しました - {e}")


# =============================================================================
# KML/KMZインポート
# =============================================================================

def import_crop_from_kml(
    state: dict,
    file,
    field_id: int,
    year: int,
    crop_name: str
) -> Tuple[pd.DataFrame, str]:
    """
    KML/KMZから作付けポリゴンを一括インポート

    Args:
        state: ユーザー情報
        file: アップロードされたファイル（Gradio file object）
        field_id: ほ場ID
        year: 年度
        crop_name: 作物名

    Returns:
        (更新後のDataFrame, メッセージ)
    """
    user_id = get_user_id_from_state(state)
    if not user_id:
        return pd.DataFrame(), format_error("エラー: ログインが必要です")

    # 入力検証
    if not file:
        df = get_crop_polygons_df(state, field_id=field_id, year=year)
        return df, format_warning("エラー: ファイルをアップロードしてください")

    if not field_id:
        df = get_crop_polygons_df(state, year=year)
        return df, format_warning("エラー: ほ場IDを指定してください")

    if not year:
        df = get_crop_polygons_df(state, field_id=field_id)
        return df, format_warning("エラー: 年度を指定してください")

    if not crop_name or not crop_name.strip():
        df = get_crop_polygons_df(state, field_id=field_id, year=year)
        return df, format_warning("エラー: 作物名を入力してください")

    # ほ場の所有者チェック
    try:
        field = FieldRepository.get_field_by_id(field_id)
        if not field or field.get("user_id") != user_id:
            df = get_crop_polygons_df(state)
            return df, format_error("エラー: このほ場にアクセスする権限がありません")
    except Exception as e:
        df = get_crop_polygons_df(state)
        return df, format_error(f"エラー: ほ場の確認に失敗しました - {e}")

    # KML/KMZパース
    try:
        # ファイルをバイト列として読み込み
        if hasattr(file, 'name'):
            # Gradio file object
            file_path = file.name
            with open(file_path, 'rb') as f:
                file_bytes = f.read()
            filename = file_path.split('/')[-1]
        else:
            # バイト列
            file_bytes = file
            filename = "uploaded.kml"

        # KML/KMZパース
        fields_data = parse_kml_or_kmz_bytes(file_bytes, filename)

        if not fields_data:
            df = get_crop_polygons_df(state, field_id=field_id, year=year)
            return df, format_warning("エラー: KML/KMZファイルにポリゴンが見つかりません")

    except Exception as e:
        df = get_crop_polygons_df(state, field_id=field_id, year=year)
        return df, format_error(f"エラー: KML/KMZの解析に失敗しました - {e}")

    # 各ポリゴンを登録
    registered_count = 0
    errors = []

    for field_data in fields_data:
        coords = field_data.get("coordinates", [])
        if len(coords) < 3:
            continue

        try:
            # 座標 → GeoJSON変換
            geojson_str = _coords_to_geojson(coords)

            # 面積計算（KMLパーサーが既に計算済みだが、GeoJSONから再計算）
            geom = geojson_to_shapely(geojson_str)
            area_ha = calculate_geodesic_area_ha(geom)

            # DB登録
            CropPolygonRepository.create(
                field_id=field_id,
                year=year,
                crop_name=crop_name.strip(),
                geometry=geojson_str,
                area_ha=area_ha,
                notes=field_data.get("name", "")
            )

            registered_count += 1

        except Exception as e:
            errors.append(f"{field_data.get('name', '不明')}: {e}")
            continue

    # 結果メッセージ
    df = get_crop_polygons_df(state, field_id=field_id, year=year)

    if registered_count > 0:
        message = format_success(f"✅ {registered_count}件の作付けポリゴンを登録しました")
        if errors:
            message += format_warning(f"\n⚠ {len(errors)}件のエラー: " + ", ".join(errors[:3]))
        return df, message
    else:
        if errors:
            return df, format_error(f"エラー: 全て失敗しました - " + ", ".join(errors[:3]))
        else:
            return df, format_warning("エラー: 登録可能なポリゴンがありませんでした")


# =============================================================================
# 前年度からコピー
# =============================================================================

def copy_previous_year(
    state: dict,
    from_year: int,
    to_year: int
) -> Tuple[pd.DataFrame, str]:
    """
    前年度の作付けポリゴンを次年度にコピー

    Args:
        state: ユーザー情報
        from_year: コピー元年度
        to_year: コピー先年度

    Returns:
        (更新後のDataFrame, メッセージ)
    """
    user_id = get_user_id_from_state(state)
    if not user_id:
        return pd.DataFrame(), format_error("エラー: ログインが必要です")

    # 入力検証
    if not from_year or not to_year:
        df = get_crop_polygons_df(state)
        return df, format_warning("エラー: コピー元年度とコピー先年度を指定してください")

    if from_year == to_year:
        df = get_crop_polygons_df(state, year=to_year)
        return df, format_warning("エラー: コピー元とコピー先の年度が同じです")

    # コピー
    try:
        count = CropPolygonRepository.copy_from_previous_year(
            user_id=user_id,
            from_year=from_year,
            to_year=to_year
        )

        df = get_crop_polygons_df(state, year=to_year)

        if count > 0:
            return df, format_success(f"✅ {from_year}年度から {to_year}年度へ {count}件コピーしました")
        else:
            return df, format_warning(f"⚠ コピー対象のポリゴンがありませんでした（{from_year}年度）")

    except Exception as e:
        df = get_crop_polygons_df(state, year=to_year)
        return df, format_error(f"エラー: コピーに失敗しました - {e}")


# =============================================================================
# 公開API
# =============================================================================

__all__ = [
    "get_crop_polygons_df",
    "register_crop_polygon",
    "delete_crop_polygon",
    "import_crop_from_kml",
    "copy_previous_year",
]
