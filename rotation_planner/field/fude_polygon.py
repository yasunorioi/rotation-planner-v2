"""
rotation_planner.field.fude_polygon - 筆ポリゴン（農水省）連携モジュール

農林水産省が公開している筆ポリゴンデータを取得・表示するための機能を提供。
筆ポリゴンは農地の区画情報で、衛星画像等をもとに筆ごとの形状に沿って作成されている。

データ出典:
    農林水産省「筆ポリゴンデータ」
    https://open.fude.maff.go.jp/

Usage:
    from rotation_planner.field.fude_polygon import (
        fetch_fude_polygon_by_location,
        get_fude_polygon_geojson_url,
    )
"""

import json
import requests
from typing import List, Dict, Optional, Tuple, Any
from pathlib import Path

# =============================================================================
# 定数
# =============================================================================

# 筆ポリゴンデータのベースURL
FUDE_POLYGON_BASE_URL = "https://habs.rad.naro.go.jp"

# PMTiles形式のURL（最新版）
PMTILES_URL = "https://habs.rad.naro.go.jp/spatial_data/fude/2024/fude_2024_h.pmtiles"

# 地方公共団体コードと都道府県名のマッピング（北海道のみ詳細）
HOKKAIDO_CITY_CODES = {
    "01100": "札幌市",
    "01202": "函館市",
    "01203": "小樽市",
    "01204": "旭川市",
    "01205": "室蘭市",
    "01206": "釧路市",
    "01207": "帯広市",
    "01208": "北見市",
    "01209": "夕張市",
    "01210": "岩見沢市",
    "01211": "網走市",
    "01212": "留萌市",
    "01213": "苫小牧市",
    "01214": "稚内市",
    "01215": "美唄市",
    "01216": "芦別市",
    "01217": "江別市",
    "01218": "赤平市",
    "01219": "紋別市",
    "01220": "士別市",
    "01221": "名寄市",
    "01222": "三笠市",
    "01223": "根室市",
    "01224": "千歳市",
    "01225": "滝川市",
    "01226": "砂川市",
    "01227": "歌志内市",
    "01228": "深川市",
    "01229": "富良野市",
    "01230": "登別市",
    "01231": "恵庭市",
    "01233": "伊達市",
    "01234": "北広島市",
    "01235": "石狩市",
    "01236": "北斗市",
    # 石狩振興局
    "01303": "当別町",
    "01304": "新篠津村",
    # 後志総合振興局
    "01331": "松前町",
    # 上川総合振興局
    "01452": "鷹栖町",
    "01453": "東神楽町",
    "01454": "当麻町",
    "01455": "比布町",
    "01456": "愛別町",
    "01457": "上川町",
    "01458": "東川町",
    "01459": "美瑛町",
    # 十勝総合振興局
    "01631": "音更町",
    "01632": "士幌町",
    "01633": "上士幌町",
    "01634": "鹿追町",
    "01635": "新得町",
    "01636": "清水町",
    "01637": "芽室町",
    "01638": "中札内村",
    "01639": "更別村",
    "01641": "大樹町",
    "01642": "広尾町",
    "01643": "幕別町",
    "01644": "池田町",
    "01645": "豊頃町",
    "01646": "本別町",
    "01647": "足寄町",
    "01648": "陸別町",
    "01649": "浦幌町",
}

# 都道府県コード
PREFECTURE_CODES = {
    "01": "北海道",
    "02": "青森県",
    "03": "岩手県",
    # ... 他の都道府県は省略
}


# =============================================================================
# 筆ポリゴンデータ取得
# =============================================================================

def get_local_government_code_from_location(lat: float, lng: float) -> Optional[str]:
    """
    緯度経度から地方公共団体コードを推定

    Note:
        これは簡易実装。実際には逆ジオコーディングAPIを使用すべき。
    """
    # 簡易的な実装: Nominatimで住所を取得し、市町村名からコードを推定
    try:
        params = {
            "lat": lat,
            "lon": lng,
            "format": "json",
            "zoom": 10,  # 市町村レベル
        }
        headers = {
            "User-Agent": "FieldRegisterApp/1.0"
        }

        response = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params=params,
            headers=headers,
            timeout=10
        )
        response.raise_for_status()

        result = response.json()
        address = result.get("address", {})

        # 北海道の場合、市町村名からコードを検索
        city = address.get("city") or address.get("town") or address.get("village")

        if city:
            for code, name in HOKKAIDO_CITY_CODES.items():
                if name in city or city in name:
                    return code

        return None

    except Exception:
        return None


def get_fude_cache_dir() -> Path:
    """筆ポリゴンキャッシュディレクトリを取得"""
    cache_dir = Path(__file__).parent.parent.parent / "data" / "fude_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def get_available_fude_files() -> List[str]:
    """利用可能な筆ポリゴンファイル一覧を取得"""
    cache_dir = get_fude_cache_dir()
    files = []
    for ext in ["*.geojson", "*.json"]:
        files.extend([f.name for f in cache_dir.glob(ext)])
    return sorted(files)


def fetch_fude_polygons_in_bbox(
    min_lat: float,
    min_lng: float,
    max_lat: float,
    max_lng: float,
    local_gov_code: Optional[str] = None,
    max_results: int = 500
) -> List[Dict[str, Any]]:
    """
    バウンディングボックス内の筆ポリゴンを取得

    Note:
        ローカルにアップロードされたGeoJSONファイルから検索。

    Args:
        min_lat: 最小緯度
        min_lng: 最小経度
        max_lat: 最大緯度
        max_lng: 最大経度
        local_gov_code: 地方公共団体コード（オプション、指定時はそのファイルのみ検索）
        max_results: 最大結果数（パフォーマンス制限）

    Returns:
        筆ポリゴンのリスト
    """
    cache_dir = get_fude_cache_dir()
    polygons = []

    # 検索対象ファイルを決定
    if local_gov_code:
        # 特定のコードが指定された場合
        search_files = [
            cache_dir / f"{local_gov_code}.geojson",
            cache_dir / f"{local_gov_code}.json",
        ]
        search_files = [f for f in search_files if f.exists()]
    else:
        # 全ファイルを検索
        search_files = list(cache_dir.glob("*.geojson")) + list(cache_dir.glob("*.json"))

    for cache_file in search_files:
        if len(polygons) >= max_results:
            break

        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                geojson = json.load(f)

            features = geojson.get("features", [])

            for feature in features:
                if len(polygons) >= max_results:
                    break

                coords = feature.get("geometry", {}).get("coordinates", [])
                if coords and _polygon_in_bbox(coords, min_lat, min_lng, max_lat, max_lng):
                    polygons.append(_feature_to_polygon_data(feature))

        except (json.JSONDecodeError, IOError):
            continue

    return polygons


def _polygon_in_bbox(
    coordinates: List,
    min_lat: float,
    min_lng: float,
    max_lat: float,
    max_lng: float
) -> bool:
    """ポリゴンがバウンディングボックス内にあるかチェック"""
    try:
        # GeoJSONのPolygon座標は [[[lng, lat], ...]]
        if not coordinates:
            return False

        ring = coordinates[0] if isinstance(coordinates[0][0], list) else coordinates

        for point in ring:
            lng, lat = point[0], point[1]
            if min_lat <= lat <= max_lat and min_lng <= lng <= max_lng:
                return True

        return False
    except (IndexError, TypeError):
        return False


def _feature_to_polygon_data(feature: Dict[str, Any]) -> Dict[str, Any]:
    """GeoJSON FeatureをアプリのPolygonデータ形式に変換"""
    props = feature.get("properties", {})
    geometry = feature.get("geometry", {})

    # GeoJSONは[lng, lat]形式、アプリは[lat, lng]形式
    coordinates = []
    raw_coords = geometry.get("coordinates", [])

    if raw_coords:
        ring = raw_coords[0] if isinstance(raw_coords[0][0], list) else raw_coords
        coordinates = [[point[1], point[0]] for point in ring]  # lat, lng に変換

    return {
        "fude_id": props.get("polygon_uuid") or props.get("id", ""),
        "local_gov_code": props.get("local_government_cd", ""),
        "land_type": props.get("land_type", ""),  # 100: 田, 200: 畑
        "area_ha": props.get("area", 0) / 10000 if props.get("area") else 0,
        "coordinates": coordinates,
        "point_count": props.get("point_count", 0),
        "issue_year": props.get("issue_year", ""),
    }


# =============================================================================
# Leaflet連携用JavaScript生成
# =============================================================================

def generate_fude_polygon_layer_js() -> str:
    """
    筆ポリゴン表示用のLeafletレイヤーJavaScriptを生成

    PMTiles形式のベクタータイルを使用して効率的に表示
    """
    return '''
    // 筆ポリゴンレイヤー（PMTiles使用）
    // Note: PMTilesを使用するにはprotomaps-leafletライブラリが必要

    var fudeLayer = null;
    var fudeVisible = false;

    // 筆ポリゴン表示切替
    window.toggleFudePolygon = function() {
        fudeVisible = !fudeVisible;
        if (fudeVisible) {
            showFudePolygonNotice();
        } else {
            hideFudePolygon();
        }
        return fudeVisible;
    };

    function showFudePolygonNotice() {
        // 筆ポリゴンはデータ量が大きいため、
        // 現在のビューポートに合わせてオンデマンドで取得
        var bounds = map.getBounds();
        var zoom = map.getZoom();

        if (zoom < 14) {
            alert('筆ポリゴンを表示するにはズームレベル14以上に拡大してください');
            fudeVisible = false;
            return;
        }

        // 通知
        console.log('筆ポリゴン表示: bounds=', bounds, 'zoom=', zoom);
    }

    function hideFudePolygon() {
        if (fudeLayer) {
            map.removeLayer(fudeLayer);
            fudeLayer = null;
        }
    }

    // クリックした筆ポリゴンを選択
    window.selectFudePolygon = function(polygon_data) {
        if (!polygon_data || !polygon_data.coordinates) return;

        // 既存の描画をクリア
        drawnItems.clearLayers();

        // 筆ポリゴンの座標で新しいポリゴンを作成
        var polygon = L.polygon(polygon_data.coordinates, {
            color: '#3388ff',
            fillColor: '#3388ff',
            fillOpacity: 0.3
        }).addTo(drawnItems);

        // 座標をGradioに送信
        var coords = polygon_data.coordinates;
        sendCoordinatesToGradio(coords);

        // 面積を更新
        var latlngs = polygon.getLatLngs()[0];
        var area_m2 = L.GeometryUtil.geodesicArea(latlngs);
        areaInfo.update(area_m2);
    };
    '''


def generate_fude_polygon_control_html() -> str:
    """筆ポリゴン操作用のHTMLコントロールを生成"""
    return '''
    <div id="fude-control" style="
        position: absolute;
        bottom: 80px;
        left: 10px;
        z-index: 1000;
        background: white;
        padding: 8px 12px;
        border-radius: 4px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.2);
    ">
        <label style="display: flex; align-items: center; cursor: pointer;">
            <input type="checkbox" id="fude-toggle" onchange="toggleFudePolygon()" style="margin-right: 8px;">
            <span>筆ポリゴン表示</span>
        </label>
        <div id="fude-info" style="font-size: 11px; color: #666; margin-top: 4px;">
            クリックでほ場を選択
        </div>
    </div>
    '''


# =============================================================================
# データダウンロード補助
# =============================================================================

def get_fude_download_url(prefecture_code: str, city_code: Optional[str] = None, year: int = 2024) -> str:
    """
    筆ポリゴンデータのダウンロードURL生成

    Note:
        実際のダウンロードには利用規約への同意が必要
        https://open.fude.maff.go.jp/

    Args:
        prefecture_code: 都道府県コード（2桁）
        city_code: 市区町村コード（5桁、オプション）
        year: データ年度

    Returns:
        ダウンロードページURL
    """
    return f"https://open.fude.maff.go.jp/download/{prefecture_code}"


def download_fude_geojson(
    local_gov_code: str,
    output_dir: Optional[Path] = None,
    year: int = 2024
) -> Optional[Path]:
    """
    筆ポリゴンGeoJSONをダウンロード（キャッシュ用）

    Note:
        農水省のダウンロードページはアンケート回答が必要なため、
        自動ダウンロードは対応していない。
        手動でダウンロードしたファイルをdata/fude_cacheに配置する。

    Args:
        local_gov_code: 地方公共団体コード（5桁）
        output_dir: 出力ディレクトリ
        year: データ年度

    Returns:
        保存先パス（ダウンロード成功時）またはNone
    """
    if output_dir is None:
        output_dir = Path(__file__).parent.parent.parent / "data" / "fude_cache"

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{local_gov_code}.geojson"

    # 既にキャッシュがある場合はそれを返す
    if output_path.exists():
        return output_path

    # 自動ダウンロードは非対応
    # 手動でダウンロードが必要なことを示す
    return None


# =============================================================================
# 公開API
# =============================================================================

__all__ = [
    # 定数
    "FUDE_POLYGON_BASE_URL",
    "PMTILES_URL",
    "HOKKAIDO_CITY_CODES",
    # 筆ポリゴン取得
    "get_local_government_code_from_location",
    "fetch_fude_polygons_in_bbox",
    # Leaflet連携
    "generate_fude_polygon_layer_js",
    "generate_fude_polygon_control_html",
    # データダウンロード
    "get_fude_download_url",
    "download_fude_geojson",
]
