"""
rotation_planner.field.gps_matcher - GPS座標からほ場を特定するモジュール

GPS座標を入力として、登録済みほ場の中から最も近いほ場を特定する。
Shapelyを使用してポイントがポリゴン内にあるか判定し、
ポリゴン外の場合は最寄りのほ場を距離順で返す。

Usage:
    from rotation_planner.field.gps_matcher import (
        find_field_by_gps,
        get_field_candidates,
    )
"""

import json
import math
from typing import List, Dict, Any, Optional, Tuple

try:
    from shapely.geometry import Point, Polygon
    from shapely.ops import nearest_points
    from shapely import STRtree
    SHAPELY_AVAILABLE = True
except ImportError:
    SHAPELY_AVAILABLE = False

from pyproj import Geod
from rotation_planner.field.spatial import _meters_to_degrees


# =============================================================================
# 定数
# =============================================================================

# WGS84楕円体（測地線計算用）
GEOD = Geod(ellps="WGS84")

# マッチング閾値（メートル）
MAX_DISTANCE_METERS = 500  # 500m以内のほ場を候補とする


# =============================================================================
# ヘルパー関数
# =============================================================================

def _parse_coordinates(coordinates_json: str) -> Optional[List[List[float]]]:
    """
    座標JSONをパースして座標リストを返す

    Args:
        coordinates_json: JSON文字列 '[[lat, lng], [lat, lng], ...]'

    Returns:
        座標リスト [[lat, lng], ...] またはNone
    """
    if not coordinates_json:
        return None

    try:
        if isinstance(coordinates_json, str):
            coords = json.loads(coordinates_json)
        else:
            coords = coordinates_json

        if isinstance(coords, list) and len(coords) >= 3:
            return coords
        return None
    except (json.JSONDecodeError, TypeError):
        return None


def _coords_to_polygon(coords: List[List[float]]) -> Optional[Polygon]:
    """
    座標リストをShapely Polygonに変換

    Args:
        coords: [[lat, lng], [lat, lng], ...] 形式の座標リスト

    Returns:
        Shapely Polygon またはNone
    """
    if not SHAPELY_AVAILABLE:
        return None

    if not coords or len(coords) < 3:
        return None

    try:
        # Shapelyは (lng, lat) = (x, y) の順
        polygon_coords = [(c[1], c[0]) for c in coords]

        # ポリゴンを閉じる
        if polygon_coords[0] != polygon_coords[-1]:
            polygon_coords.append(polygon_coords[0])

        return Polygon(polygon_coords)
    except Exception:
        return None


def _calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    2点間の測地線距離を計算（メートル）

    Args:
        lat1, lon1: 点1の緯度・経度
        lat2, lon2: 点2の緯度・経度

    Returns:
        距離（メートル）
    """
    try:
        _, _, distance = GEOD.inv(lon1, lat1, lon2, lat2)
        return abs(distance)
    except Exception:
        # フォールバック: 簡易計算（球面近似）
        R = 6371000  # 地球の半径（メートル）
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)

        a = math.sin(dlat / 2) ** 2 + \
            math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c


def _get_polygon_centroid(coords: List[List[float]]) -> Tuple[float, float]:
    """
    ポリゴンの重心を計算

    Args:
        coords: [[lat, lng], ...] 形式の座標リスト

    Returns:
        (lat, lng) の重心座標
    """
    if not coords:
        return (0.0, 0.0)

    lat_sum = sum(c[0] for c in coords)
    lng_sum = sum(c[1] for c in coords)
    n = len(coords)

    return (lat_sum / n, lng_sum / n)


# =============================================================================
# メイン機能
# =============================================================================

def find_field_by_gps(
    gps_lat: float,
    gps_lon: float,
    fields: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """
    GPS座標が含まれるほ場を特定

    Args:
        gps_lat: GPS緯度
        gps_lon: GPS経度
        fields: ほ場データのリスト（coordinates_jsonを含む）

    Returns:
        マッチしたほ場の辞書、またはNone
    """
    if not SHAPELY_AVAILABLE:
        return None

    point = Point(gps_lon, gps_lat)  # Shapelyは (x, y) = (lng, lat)

    # ほ場とポリゴンのペアを構築
    valid_entries = []
    polygons = []
    for field in fields:
        coords = _parse_coordinates(field.get("coordinates_json"))
        if not coords:
            continue
        polygon = _coords_to_polygon(coords)
        if polygon:
            valid_entries.append(field)
            polygons.append(polygon)

    if not polygons:
        return None

    tree = STRtree(polygons)
    hits = tree.query(point, predicate='covered_by')
    if len(hits) > 0:
        return valid_entries[hits[0]]

    return None


def get_field_candidates(
    gps_lat: float,
    gps_lon: float,
    fields: List[Dict[str, Any]],
    max_results: int = 5,
    max_distance: float = MAX_DISTANCE_METERS
) -> List[Dict[str, Any]]:
    """
    GPS座標から近いほ場候補を距離順で取得

    まずポリゴン内にあるか判定し、なければ最寄りのほ場を
    距離順でリストアップする。

    Args:
        gps_lat: GPS緯度
        gps_lon: GPS経度
        fields: ほ場データのリスト（coordinates_jsonを含む）
        max_results: 返す最大件数
        max_distance: 候補とする最大距離（メートル）

    Returns:
        候補ほ場のリスト。各要素は元のほ場dictに以下を追加:
        - distance_m: GPSからの距離（メートル）
        - is_inside: GPSがポリゴン内にあるか
    """
    if not fields:
        return []

    point = Point(gps_lon, gps_lat) if SHAPELY_AVAILABLE else None

    # Shapely利用可能時: STRtreeで空間絞り込み
    if SHAPELY_AVAILABLE and point:
        # 有効なほ場・ポリゴン・座標を構築
        valid_entries = []
        polygons = []
        coords_list = []
        for field in fields:
            coords = _parse_coordinates(field.get("coordinates_json"))
            if not coords:
                continue
            polygon = _coords_to_polygon(coords)
            if polygon:
                valid_entries.append(field)
                polygons.append(polygon)
                coords_list.append(coords)

        if not polygons:
            return []

        tree = STRtree(polygons)

        # contains判定（ほ場内にいるケース）
        inside_hits = set(tree.query(point, predicate='covered_by'))

        # バッファ範囲内の候補に絞ってから距離計算
        buf_deg = _meters_to_degrees(max_distance)
        search_area = point.buffer(buf_deg)
        nearby_hits = tree.query(search_area, predicate='intersects')

        # inside_hitsとnearby_hitsを合わせた候補のみ処理
        candidate_indices = set(nearby_hits) | inside_hits

        candidates = []
        for idx in candidate_indices:
            field = valid_entries[idx]
            polygon = polygons[idx]
            coords = coords_list[idx]
            is_inside = idx in inside_hits

            if is_inside:
                distance_m = 0.0
            else:
                try:
                    nearest_pt = nearest_points(point, polygon)[1]
                    distance_m = _calculate_distance(
                        gps_lat, gps_lon,
                        nearest_pt.y, nearest_pt.x
                    )
                except Exception:
                    centroid = _get_polygon_centroid(coords)
                    distance_m = _calculate_distance(
                        gps_lat, gps_lon,
                        centroid[0], centroid[1]
                    )

            if distance_m <= max_distance or is_inside:
                candidate = field.copy()
                candidate["distance_m"] = round(distance_m, 1)
                candidate["is_inside"] = is_inside
                candidates.append(candidate)
    else:
        # Shapely未使用時: 重心までの距離で代用（フォールバック）
        candidates = []
        for field in fields:
            coords = _parse_coordinates(field.get("coordinates_json"))
            if not coords:
                continue

            centroid = _get_polygon_centroid(coords)
            distance_m = _calculate_distance(
                gps_lat, gps_lon,
                centroid[0], centroid[1]
            )

            if distance_m <= max_distance:
                candidate = field.copy()
                candidate["distance_m"] = round(distance_m, 1)
                candidate["is_inside"] = False
                candidates.append(candidate)

    # 距離順でソート（内部にあるものを優先）
    candidates.sort(key=lambda c: (not c["is_inside"], c["distance_m"]))

    return candidates[:max_results]


def format_field_candidates_for_display(
    candidates: List[Dict[str, Any]]
) -> List[Tuple[str, int]]:
    """
    候補ほ場をGradio Dropdown用の形式に変換

    Args:
        candidates: get_field_candidates()の結果

    Returns:
        [(表示名, field_id), ...] のリスト
    """
    result = []

    for c in candidates:
        field_code = c.get("field_code", "")
        field_name = c.get("name", "")
        distance_m = c.get("distance_m", 0)
        is_inside = c.get("is_inside", False)

        if is_inside:
            distance_text = "現在地"
        elif distance_m < 1000:
            distance_text = f"{int(distance_m)}m"
        else:
            distance_text = f"{distance_m / 1000:.1f}km"

        display_name = f"{field_code} {field_name}".strip()
        display_name = f"{display_name} ({distance_text})"

        result.append((display_name, c.get("id")))

    return result


# =============================================================================
# 公開API
# =============================================================================

__all__ = [
    "SHAPELY_AVAILABLE",
    "MAX_DISTANCE_METERS",
    "find_field_by_gps",
    "get_field_candidates",
    "format_field_candidates_for_display",
]
