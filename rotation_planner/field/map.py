"""
rotation_planner.field.map - Leaflet地図連携・面積計算モジュール

Leaflet.jsを使った地図表示、ポリゴン描画、
WGS84楕円体による面積計算、住所検索機能を提供。

Usage:
    from rotation_planner.field.map import (
        generate_map_html,
        calculate_area_from_coords,
        m2_to_ha,
        m2_to_a,
        search_address,
    )
"""

import json
import os
import requests
from typing import List, Dict, Optional, Tuple, Any
from pyproj import Geod

# デバッグモード（環境変数で制御、デフォルトON）
DEBUG_MODE = os.environ.get('DEBUG', '1') == '1'

# =============================================================================
# 定数
# =============================================================================

# 北海道の初期位置（JA道央本店 - 恵庭市島松仲町）
DEFAULT_LAT = 42.919253
DEFAULT_LNG = 141.574635
DEFAULT_ZOOM = 14

# Nominatim API エンドポイント
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


# =============================================================================
# 面積計算
# =============================================================================

def calculate_area_from_coords(coordinates: List[List[float]]) -> float:
    """
    座標リストから面積を計算（平方メートル）
    WGS84楕円体上の面積を正確に計算

    Args:
        coordinates: [[lat, lng], [lat, lng], ...] 形式の座標リスト

    Returns:
        面積（平方メートル）
    """
    if len(coordinates) < 3:
        return 0.0

    # 座標を (lng, lat) 形式に変換（Shapelyは経度,緯度の順）
    coords_lnglat = [(coord[1], coord[0]) for coord in coordinates]

    # ポリゴンを閉じる
    if coords_lnglat[0] != coords_lnglat[-1]:
        coords_lnglat.append(coords_lnglat[0])

    # Geod（測地線計算）を使用して面積を計算
    geod = Geod(ellps="WGS84")

    # polygon_area_perimeter は (面積, 周長) を返す
    # 面積は符号付きで返されるので abs() を使用
    lons = [c[0] for c in coords_lnglat]
    lats = [c[1] for c in coords_lnglat]
    area_m2, _ = geod.polygon_area_perimeter(lons, lats)

    return abs(area_m2)


def m2_to_a(m2: float) -> float:
    """平方メートルをアールに変換"""
    return m2 / 100.0


def m2_to_ha(m2: float) -> float:
    """平方メートルをヘクタールに変換"""
    return m2 / 10000.0


# =============================================================================
# 住所検索
# =============================================================================

def search_address(query: str) -> Tuple[Optional[float], Optional[float], str]:
    """
    住所・地名からNominatim APIで座標を検索

    Args:
        query: 検索する住所・地名

    Returns:
        (lat, lng, message) のタプル
    """
    if not query.strip():
        return None, None, "検索語を入力してください"

    try:
        params = {
            "q": query,
            "format": "json",
            "limit": 1,
            "countrycodes": "jp",  # 日本に限定
        }
        headers = {
            "User-Agent": "FieldRegisterApp/1.0"  # Nominatim利用規約に準拠
        }

        response = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=10)
        response.raise_for_status()

        results = response.json()

        if results:
            lat = float(results[0]["lat"])
            lng = float(results[0]["lon"])
            display_name = results[0].get("display_name", query)
            return lat, lng, f"検索結果: {display_name}"
        else:
            return None, None, f"「{query}」の検索結果が見つかりません"

    except requests.exceptions.Timeout:
        return None, None, "検索がタイムアウトしました"
    except requests.exceptions.RequestException as e:
        return None, None, f"検索エラー: {str(e)}"
    except Exception as e:
        return None, None, f"予期しないエラー: {str(e)}"


# =============================================================================
# Leaflet HTML/JS 生成
# =============================================================================

def generate_map_html(
    center_lat: float = DEFAULT_LAT,
    center_lng: float = DEFAULT_LNG,
    zoom: int = DEFAULT_ZOOM,
    existing_fields: List[Dict[str, Any]] = None,
    fude_polygons: List[Dict[str, Any]] = None
) -> str:
    """
    Leaflet地図のHTMLを生成

    Args:
        center_lat: 地図中心の緯度
        center_lng: 地図中心の経度
        zoom: ズームレベル
        existing_fields: 表示する既存ほ場のリスト
        fude_polygons: 表示する筆ポリゴンのリスト

    Returns:
        Leaflet地図のHTML文字列
    """

    existing_fields = existing_fields or []
    fude_polygons = fude_polygons or []

    # 既存ほ場のポリゴンデータをJSON形式で埋め込む
    fields_json = json.dumps([
        {
            "field_id": f.get("field_code", f.get("id", "")),
            "name": f.get("name", ""),
            "coordinates": json.loads(f.get("coordinates_json", "[]")) if isinstance(f.get("coordinates_json"), str) else f.get("coordinates_json", []),
            "area_a": f.get("area_a", f.get("area_ha", 0) * 100)
        }
        for f in existing_fields
        if f.get("coordinates_json")
    ])

    # 筆ポリゴンデータをJSON形式で埋め込む
    fude_json = json.dumps(fude_polygons)

    # デバッグフラグをJavaScriptに渡す
    debug_js = 'true' if DEBUG_MODE else 'false'

    # iframe の srcdoc に埋め込むため、HTMLをエスケープしない形式で生成
    inner_html = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet.draw/1.0.4/leaflet.draw.css" />
    <script>var DEBUG = {debug_js};</script>
    <style>
        body {{ margin: 0; padding: 0; }}
        #map {{
            width: 100%;
            height: 500px;
            border: 2px solid #ccc;
            border-radius: 8px;
        }}
        .area-display {{
                background: white;
                padding: 10px;
                border-radius: 5px;
                box-shadow: 0 2px 5px rgba(0,0,0,0.2);
            }}
            .field-popup {{
                min-width: 150px;
            }}
        </style>
    </head>
    <body>
        <div id="map"></div>

        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet.draw/1.0.4/leaflet.draw.js"></script>
        <script>
            // 地図初期化
            var map = L.map('map').setView([{center_lat}, {center_lng}], {zoom});

            // ベースレイヤー定義
            var osmLayer = L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
                maxZoom: 19
            }});

            // Esri World Imagery（比較的新しい衛星画像）
            var esriSatelliteLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}', {{
                attribution: '&copy; <a href="https://www.esri.com/">Esri</a>, Maxar, Earthstar Geographics',
                maxZoom: 19
            }});

            // 国土地理院 航空写真
            var gsiPhotoLayer = L.tileLayer('https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/{{z}}/{{x}}/{{y}}.jpg', {{
                attribution: '&copy; <a href="https://maps.gsi.go.jp/development/ichiran.html">国土地理院</a>',
                maxZoom: 18
            }});

            // 国土地理院 標準地図
            var gsiStdLayer = L.tileLayer('https://cyberjapandata.gsi.go.jp/xyz/std/{{z}}/{{x}}/{{y}}.png', {{
                attribution: '&copy; <a href="https://maps.gsi.go.jp/development/ichiran.html">国土地理院</a>',
                maxZoom: 18
            }});

            // デフォルトはEsri衛星画像（新しい）
            esriSatelliteLayer.addTo(map);

            // レイヤー切り替えコントロール
            var baseLayers = {{
                "衛星写真（Esri）": esriSatelliteLayer,
                "航空写真（国土地理院）": gsiPhotoLayer,
                "地図（国土地理院）": gsiStdLayer,
                "OpenStreetMap": osmLayer
            }};
            L.control.layers(baseLayers, {{}}, {{position: 'topright'}}).addTo(map);

            // 描画レイヤー
            var drawnItems = new L.FeatureGroup();
            map.addLayer(drawnItems);

            // 既存ほ場レイヤー
            var existingFields = new L.FeatureGroup();
            map.addLayer(existingFields);

            // 描画コントロール
            var drawControl = new L.Control.Draw({{
                position: 'topright',
                draw: {{
                    polygon: {{
                        allowIntersection: false,
                        showArea: true,
                        shapeOptions: {{
                            color: '#3388ff',
                            fillColor: '#3388ff',
                            fillOpacity: 0.3
                        }}
                    }},
                    polyline: false,
                    circle: false,
                    rectangle: false,
                    marker: false,
                    circlemarker: false
                }},
                edit: {{
                    featureGroup: drawnItems,
                    remove: true,
                    edit: true
                }}
            }});
            map.addControl(drawControl);

            // 面積表示コントロール
            var areaInfo = L.control({{position: 'bottomright'}});
            areaInfo.onAdd = function(map) {{
                this._div = L.DomUtil.create('div', 'area-display');
                this.update();
                return this._div;
            }};
            areaInfo.update = function(area_m2) {{
                if (area_m2) {{
                    var area_a = (area_m2 / 100).toFixed(2);
                    var area_ha = (area_m2 / 10000).toFixed(4);
                    this._div.innerHTML = '<b>描画中の面積</b><br>' +
                        area_a + ' a<br>' +
                        area_ha + ' ha';
                }} else {{
                    this._div.innerHTML = '<b>面積</b><br>ポリゴンを描画してください';
                }}
            }};
            areaInfo.addTo(map);

            // 現在描画中のポリゴン座標
            var currentPolygonCoords = null;

            // ポリゴン作成完了イベント
            map.on(L.Draw.Event.CREATED, function(event) {{
                var layer = event.layer;
                drawnItems.clearLayers();  // 1つだけ描画可能
                drawnItems.addLayer(layer);

                // 座標を取得
                var latlngs = layer.getLatLngs()[0];
                currentPolygonCoords = latlngs.map(function(ll) {{
                    return [ll.lat, ll.lng];
                }});

                // 面積計算（クライアント側の概算）
                var area_m2 = L.GeometryUtil.geodesicArea(latlngs);
                areaInfo.update(area_m2);

                // Gradioに座標を送信
                sendCoordinatesToGradio(currentPolygonCoords);
            }});

            // ポリゴン編集完了イベント
            map.on(L.Draw.Event.EDITED, function(event) {{
                var layers = event.layers;
                layers.eachLayer(function(layer) {{
                    var latlngs = layer.getLatLngs()[0];
                    currentPolygonCoords = latlngs.map(function(ll) {{
                        return [ll.lat, ll.lng];
                    }});

                    var area_m2 = L.GeometryUtil.geodesicArea(latlngs);
                    areaInfo.update(area_m2);

                    sendCoordinatesToGradio(currentPolygonCoords);
                }});
            }});

            // ポリゴン削除イベント
            map.on(L.Draw.Event.DELETED, function(event) {{
                currentPolygonCoords = null;
                areaInfo.update(null);
                sendCoordinatesToGradio(null);
            }});

            // Gradioへ座標送信
            function sendCoordinatesToGradio(coords) {{
                var coordsJson = coords ? JSON.stringify(coords) : '';

                // 親ウィンドウのGradio textboxに直接アクセス
                try {{
                    if (window.parent && window.parent !== window) {{
                        var coordsInput = window.parent.document.querySelector('#coords_input textarea');
                        if (coordsInput) {{
                            coordsInput.value = coordsJson;
                            coordsInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            console.log('Coordinates sent to Gradio:', coordsJson.substring(0, 50) + '...');
                        }} else {{
                            console.warn('coords_input textarea not found in parent');
                        }}
                    }}
                }} catch (e) {{
                    console.error('Failed to send coordinates to Gradio:', e);
                    // フォールバック: postMessage
                    window.parent.postMessage({{
                        type: 'polygon_coordinates',
                        coordinates: coordsJson
                    }}, '*');
                }}
            }}

            // 既存ほ場を表示
            var existingData = {fields_json};
            existingData.forEach(function(field) {{
                if (field.coordinates && field.coordinates.length > 0) {{
                    var polygon = L.polygon(field.coordinates, {{
                        color: '#28a745',
                        fillColor: '#28a745',
                        fillOpacity: 0.3
                    }}).addTo(existingFields);

                    polygon.bindPopup(
                        '<div class="field-popup">' +
                        '<b>' + field.field_id + '</b><br>' +
                        field.name + '<br>' +
                        field.area_a.toFixed(2) + ' a' +
                        '</div>'
                    );
                }}
            }});

            // 地図の中心移動関数（外部から呼び出し用）
            window.moveMapTo = function(lat, lng, zoom) {{
                map.setView([lat, lng], zoom || 15);
            }};

            // 現在の座標を取得する関数
            window.getCurrentCoords = function() {{
                return currentPolygonCoords ? JSON.stringify(currentPolygonCoords) : '';
            }};

            // ポリゴンをクリアする関数
            window.clearDrawnPolygon = function() {{
                drawnItems.clearLayers();
                currentPolygonCoords = null;
                areaInfo.update(null);
            }};

            // 既存ほ場を更新する関数
            window.updateExistingFields = function(fieldsData) {{
                existingFields.clearLayers();
                var fields = JSON.parse(fieldsData);
                fields.forEach(function(field) {{
                    if (field.coordinates && field.coordinates.length > 0) {{
                        var polygon = L.polygon(field.coordinates, {{
                            color: '#28a745',
                            fillColor: '#28a745',
                            fillOpacity: 0.3
                        }}).addTo(existingFields);

                        polygon.bindPopup(
                            '<div class="field-popup">' +
                            '<b>' + field.field_id + '</b><br>' +
                            field.name + '<br>' +
                            field.area_a.toFixed(2) + ' a' +
                            '</div>'
                        );
                    }}
                }});
            }};

            // =============================================================================
            // 筆ポリゴン機能（農水省データ）
            // =============================================================================

            var fudeLayer = new L.FeatureGroup();
            map.addLayer(fudeLayer);
            var fudeVisible = false;
            var fudeData = [];

            // 筆ポリゴン表示コントロール
            var fudeControl = L.control({{position: 'bottomleft'}});
            fudeControl.onAdd = function(map) {{
                var div = L.DomUtil.create('div', 'fude-control');
                div.innerHTML = '<div style="background: white; padding: 8px 12px; border-radius: 4px; box-shadow: 0 2px 5px rgba(0,0,0,0.2);">' +
                    '<label style="display: flex; align-items: center; cursor: pointer;">' +
                    '<input type="checkbox" id="fude-toggle" style="margin-right: 8px;">' +
                    '<span style="font-size: 12px;">筆ポリゴン</span>' +
                    '</label>' +
                    '<div id="fude-info" style="font-size: 10px; color: #666; margin-top: 4px;">クリックで選択</div>' +
                    '</div>';
                L.DomEvent.disableClickPropagation(div);

                div.querySelector('#fude-toggle').addEventListener('change', function(e) {{
                    fudeVisible = e.target.checked;
                    if (fudeVisible) {{
                        loadFudePolygons();
                    }} else {{
                        fudeLayer.clearLayers();
                    }}
                }});

                return div;
            }};
            fudeControl.addTo(map);

            // 埋め込み筆ポリゴンデータ
            var embeddedFudeData = {fude_json};

            // 筆ポリゴンをロード
            function loadFudePolygons() {{
                var zoom = map.getZoom();
                var infoDiv = document.getElementById('fude-info');

                if (zoom < 15) {{
                    infoDiv.textContent = 'ズーム15以上で表示';
                    fudeLayer.clearLayers();
                    return;
                }}

                infoDiv.textContent = '読込中...';

                // 埋め込みデータを使用
                if (embeddedFudeData && embeddedFudeData.length > 0) {{
                    displayFudePolygons(embeddedFudeData);
                    infoDiv.textContent = embeddedFudeData.length + '筆 (クリックで選択)';
                }} else {{
                    infoDiv.textContent = 'データなし';
                }}
            }}

            // 筆ポリゴンを表示
            function displayFudePolygons(polygons) {{
                fudeLayer.clearLayers();
                fudeData = polygons || [];

                fudeData.forEach(function(fude) {{
                    if (fude.coordinates && fude.coordinates.length > 0) {{
                        var polygon = L.polygon(fude.coordinates, {{
                            color: '#ff6600',
                            fillColor: '#ff6600',
                            fillOpacity: 0.2,
                            weight: 1
                        }}).addTo(fudeLayer);

                        // クリックで選択
                        polygon.on('click', function() {{
                            selectFudePolygon(fude);
                        }});

                        // ホバーでハイライト
                        polygon.on('mouseover', function() {{
                            this.setStyle({{fillOpacity: 0.5}});
                        }});
                        polygon.on('mouseout', function() {{
                            this.setStyle({{fillOpacity: 0.2}});
                        }});

                        // ポップアップ
                        var areaHa = fude.area_ha || 0;
                        var landType = fude.land_type == '100' ? '田' : (fude.land_type == '200' ? '畑' : '');
                        polygon.bindPopup(
                            '<div class="field-popup">' +
                            '<b>筆ポリゴン</b><br>' +
                            (landType ? landType + '<br>' : '') +
                            (areaHa ? areaHa.toFixed(4) + ' ha<br>' : '') +
                            '<button onclick="window.selectFudePolygon(' + JSON.stringify(fude).replace(/"/g, '&quot;') + ')">このほ場を選択</button>' +
                            '</div>'
                        );
                    }}
                }});
            }}

            // 筆ポリゴンを選択（描画レイヤーにコピー）
            window.selectFudePolygon = function(fude) {{
                if (!fude || !fude.coordinates) return;

                // 既存の描画をクリア
                drawnItems.clearLayers();

                // 筆ポリゴンの座標で新しいポリゴンを作成
                var polygon = L.polygon(fude.coordinates, {{
                    color: '#3388ff',
                    fillColor: '#3388ff',
                    fillOpacity: 0.3
                }}).addTo(drawnItems);

                // 座標をセット
                currentPolygonCoords = fude.coordinates;

                // Gradioに座標を送信
                sendCoordinatesToGradio(currentPolygonCoords);

                // 面積を更新
                var latlngs = polygon.getLatLngs()[0];
                var area_m2 = L.GeometryUtil.geodesicArea(latlngs);
                areaInfo.update(area_m2);

                // ポップアップを閉じる
                map.closePopup();
            }};

            // 地図移動時に筆ポリゴンを再読込
            map.on('moveend', function() {{
                if (fudeVisible) {{
                    loadFudePolygons();
                }}
            }});

            // 筆ポリゴンを手動で設定（外部から呼び出し）
            window.setFudePolygons = function(polygons) {{
                displayFudePolygons(polygons);
            }};
        </script>
    </body>
    </html>'''

    # iframe で囲んで、Gradio の HTML 更新時にもスクリプトが実行されるようにする
    import html as html_module
    escaped_html = html_module.escape(inner_html)

    iframe_html = f'''<iframe
        srcdoc="{escaped_html}"
        style="width: 100%; height: 520px; border: none;"
        sandbox="allow-scripts allow-same-origin"
    ></iframe>'''

    return iframe_html


# =============================================================================
# 公開API
# =============================================================================

__all__ = [
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
]
