"""
rotation_planner.field - ほ場管理モジュール

Leaflet地図と連携したほ場登録・管理機能。
ポリゴン描画による面積自動計算、作付履歴管理。
筆ポリゴン（農水省）連携によるほ場自動取得。

主要機能:
    - 地図上でのポリゴン描画・編集
    - WGS84楕円体による面積計算
    - 住所・地名検索（Nominatim API）
    - CSV出力（輪作計画メーカー連携）
    - 作付履歴の表示・管理
    - 筆ポリゴン表示・選択

モジュール構成:
    - map.py: Leaflet地図連携、ポリゴン処理、面積計算
    - crud.py: ほ場CRUD操作（DB連携）
    - ui.py: Gradio UIコンポーネント
    - fude_polygon.py: 筆ポリゴン（農水省）連携

Usage:
    from rotation_planner.field import (
        create_field_register_ui,
        calculate_area_from_coords,
        m2_to_ha,
        m2_to_a,
    )

    # UIコンポーネントを作成
    components = create_field_register_ui(user_state)

    # 面積計算
    coords = [[43.0, 141.0], [43.1, 141.0], [43.1, 141.1], [43.0, 141.1]]
    area_m2 = calculate_area_from_coords(coords)
    area_ha = m2_to_ha(area_m2)
"""

# 地図モジュール
from .map import (
    # 定数
    DEFAULT_LAT,
    DEFAULT_LNG,
    DEFAULT_ZOOM,
    NOMINATIM_URL,
    # 面積計算
    calculate_area_from_coords,
    m2_to_a,
    m2_to_ha,
    # 住所検索
    search_address,
    # 地図生成
    generate_map_html,
)

# CRUDモジュール
from .crud import (
    # ヘルパー
    get_user_id_from_state,
    get_username_from_state,
    get_user_id_from_username,
    # データ取得
    get_user_fields,
    fields_to_dataframe,
    get_fields_json_for_map,
    # CRUD操作
    register_field_with_state,
    delete_field_with_state,
    # 履歴
    get_field_history_with_state,
    # CSV出力
    export_csv_with_state,
)

# UIモジュール（Gradio UI は削除済み。React版へ移行）

# KML/KMZパーサー・エクスポートモジュール
from .kml_parser import (
    # インポート
    parse_kml_content,
    parse_kml_file,
    parse_kmz_file,
    parse_kml_or_kmz,
    parse_kml_or_kmz_bytes,
    fields_to_dataframe_format,
    # エクスポート
    generate_kml_content,
    export_fields_to_kml,
    export_fields_to_kmz,
)

# 作物設定モジュール（Gradio UI は削除済み。React版へ移行）

# ほ場一覧UIモジュール（Gradio UI は削除済み。React版へ移行）

# 筆ポリゴンモジュール
from .fude_polygon import (
    # 定数
    FUDE_POLYGON_BASE_URL,
    PMTILES_URL,
    HOKKAIDO_CITY_CODES,
    # キャッシュ管理
    get_fude_cache_dir,
    get_available_fude_files,
    # 筆ポリゴン取得
    get_local_government_code_from_location,
    fetch_fude_polygons_in_bbox,
    # Leaflet連携
    generate_fude_polygon_layer_js,
    generate_fude_polygon_control_html,
    # データダウンロード
    get_fude_download_url,
    download_fude_geojson,
)

# GPSマッチングモジュール
from .gps_matcher import (
    SHAPELY_AVAILABLE,
    MAX_DISTANCE_METERS,
    find_field_by_gps,
    get_field_candidates,
    format_field_candidates_for_display,
)

# 公開API
__all__ = [
    # KML/KMZパーサー
    "parse_kml_content",
    "parse_kml_file",
    "parse_kmz_file",
    "parse_kml_or_kmz",
    "parse_kml_or_kmz_bytes",
    "fields_to_dataframe_format",
    # 定数
    "DEFAULT_LAT",
    "DEFAULT_LNG",
    "DEFAULT_ZOOM",
    "NOMINATIM_URL",
    # 面積計算
    "calculate_area_from_coords",
    "m2_to_a",
    "m2_to_ha",
    # 住所検索
    "search_address",
    # 地図生成
    "generate_map_html",
    # ヘルパー
    "get_user_id_from_state",
    "get_username_from_state",
    "get_user_id_from_username",
    # データ取得
    "get_user_fields",
    "fields_to_dataframe",
    "get_fields_json_for_map",
    # CRUD操作
    "register_field_with_state",
    "delete_field_with_state",
    # 履歴
    "get_field_history_with_state",
    # CSV出力
    "export_csv_with_state",
    # UI（削除済み）
    # 筆ポリゴン
    "FUDE_POLYGON_BASE_URL",
    "PMTILES_URL",
    "HOKKAIDO_CITY_CODES",
    "get_fude_cache_dir",
    "get_available_fude_files",
    "get_local_government_code_from_location",
    "fetch_fude_polygons_in_bbox",
    "generate_fude_polygon_layer_js",
    "generate_fude_polygon_control_html",
    "get_fude_download_url",
    "download_fude_geojson",
    # ほ場一覧UI（削除済み）
    # GPSマッチング
    "SHAPELY_AVAILABLE",
    "MAX_DISTANCE_METERS",
    "find_field_by_gps",
    "get_field_candidates",
    "format_field_candidates_for_display",
]
