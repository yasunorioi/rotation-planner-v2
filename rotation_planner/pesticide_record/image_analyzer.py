"""
画像解析モジュール

EXIF情報の抽出とClaude Vision APIによる農薬名認識を提供。
"""

import base64
import os
from datetime import datetime
from typing import Dict, Any, Optional

# Pillow for EXIF extraction
try:
    from PIL import Image
    from PIL.ExifTags import TAGS, GPSTAGS
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# Anthropic SDK for Vision API
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False


def _get_exif_value(exif_data: Dict, tag_name: str) -> Optional[Any]:
    """EXIF辞書から指定タグの値を取得"""
    for tag_id, value in exif_data.items():
        tag = TAGS.get(tag_id, tag_id)
        if tag == tag_name:
            return value
    return None


def _convert_gps_to_degrees(gps_coords, gps_ref: str) -> Optional[float]:
    """GPS座標を度数に変換

    Args:
        gps_coords: (degrees, minutes, seconds) のタプル
        gps_ref: 'N', 'S', 'E', 'W'

    Returns:
        緯度または経度（度数）
    """
    if not gps_coords:
        return None

    try:
        # IFDRational or tuple
        if hasattr(gps_coords[0], 'numerator'):
            # PIL.TiffImagePlugin.IFDRational
            d = float(gps_coords[0])
            m = float(gps_coords[1])
            s = float(gps_coords[2])
        else:
            d, m, s = gps_coords

        degrees = d + (m / 60.0) + (s / 3600.0)

        if gps_ref in ('S', 'W'):
            degrees = -degrees

        return round(degrees, 6)
    except (TypeError, ValueError, IndexError):
        return None


def extract_exif(image_path: str) -> Dict[str, Any]:
    """画像からEXIF情報を抽出

    Args:
        image_path: 画像ファイルのパス

    Returns:
        {
            "datetime": "2026-02-01 10:30:00" or None,
            "gps": {"lat": 43.xxx, "lon": 141.xxx} or None,
            "error": "エラーメッセージ" (エラー時のみ)
        }
    """
    result = {
        "datetime": None,
        "gps": None
    }

    if not PIL_AVAILABLE:
        result["error"] = "Pillow がインストールされていません"
        return result

    if not os.path.exists(image_path):
        result["error"] = f"ファイルが見つかりません: {image_path}"
        return result

    try:
        with Image.open(image_path) as img:
            exif_data = img._getexif()

            if not exif_data:
                result["error"] = "EXIF情報がありません"
                return result

            # 撮影日時を取得
            datetime_original = _get_exif_value(exif_data, 'DateTimeOriginal')
            if datetime_original:
                # EXIF形式: "2026:02:01 10:30:00" → "2026-02-01 10:30:00"
                try:
                    dt = datetime.strptime(datetime_original, "%Y:%m:%d %H:%M:%S")
                    result["datetime"] = dt.strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:
                    result["datetime"] = datetime_original

            # GPS情報を取得
            gps_info = _get_exif_value(exif_data, 'GPSInfo')
            if gps_info:
                gps_data = {}
                for key, val in gps_info.items():
                    gps_tag = GPSTAGS.get(key, key)
                    gps_data[gps_tag] = val

                lat = _convert_gps_to_degrees(
                    gps_data.get('GPSLatitude'),
                    gps_data.get('GPSLatitudeRef', 'N')
                )
                lon = _convert_gps_to_degrees(
                    gps_data.get('GPSLongitude'),
                    gps_data.get('GPSLongitudeRef', 'E')
                )

                if lat is not None and lon is not None:
                    result["gps"] = {"lat": lat, "lon": lon}

    except Exception as e:
        result["error"] = f"EXIF解析エラー: {str(e)}"

    return result


def recognize_pesticide_name(image_path: str) -> Dict[str, Any]:
    """Claude Vision APIで農薬名を認識

    Args:
        image_path: 画像ファイルのパス

    Returns:
        {
            "pesticide_name": "xxx" or None,
            "confidence": "high" / "medium" / "low",
            "raw_response": "APIからの生の応答",
            "error": "エラーメッセージ" (エラー時のみ)
        }
    """
    result = {
        "pesticide_name": None,
        "confidence": None,
        "raw_response": None
    }

    if not ANTHROPIC_AVAILABLE:
        result["error"] = "anthropic パッケージがインストールされていません"
        return result

    if not os.path.exists(image_path):
        result["error"] = f"ファイルが見つかりません: {image_path}"
        return result

    # API キーの確認
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        result["error"] = "ANTHROPIC_API_KEY が設定されていません"
        return result

    try:
        # 画像をBase64エンコード
        with open(image_path, "rb") as f:
            image_data = base64.standard_b64encode(f.read()).decode("utf-8")

        # 画像のMIMEタイプを判定
        ext = os.path.splitext(image_path)[1].lower()
        media_type_map = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.webp': 'image/webp',
        }
        media_type = media_type_map.get(ext, 'image/jpeg')

        # Claude Vision API 呼び出し
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=256,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data
                        }
                    },
                    {
                        "type": "text",
                        "text": """この画像から農薬名を抽出してください。
以下の形式で回答してください:
農薬名: [農薬名]
確信度: high/medium/low

農薬名が読み取れない場合は「農薬名: 不明」と回答してください。"""
                    }
                ]
            }]
        )

        # 応答を解析
        response_text = message.content[0].text
        result["raw_response"] = response_text

        # 農薬名を抽出
        for line in response_text.split('\n'):
            line = line.strip()
            if line.startswith('農薬名:') or line.startswith('農薬名：'):
                name = line.split(':', 1)[-1].split('：', 1)[-1].strip()
                if name and name != '不明':
                    result["pesticide_name"] = name

            if line.startswith('確信度:') or line.startswith('確信度：'):
                conf = line.split(':', 1)[-1].split('：', 1)[-1].strip().lower()
                if conf in ('high', 'medium', 'low'):
                    result["confidence"] = conf

        # 確信度のデフォルト
        if result["pesticide_name"] and not result["confidence"]:
            result["confidence"] = "medium"

    except anthropic.APIError as e:
        result["error"] = f"API エラー: {str(e)}"
    except Exception as e:
        result["error"] = f"認識エラー: {str(e)}"

    return result


def analyze_image(image_path: str) -> Dict[str, Any]:
    """画像を総合的に解析

    EXIF情報の抽出とVision APIによる農薬名認識を統合実行。

    Args:
        image_path: 画像ファイルのパス

    Returns:
        {
            "spray_date": "2026-02-01" or None,
            "spray_datetime": "2026-02-01 10:30:00" or None,
            "gps": {"lat": 43.xxx, "lon": 141.xxx} or None,
            "pesticide_name": "xxx" or None,
            "confidence": "high" / "medium" / "low" or None,
            "errors": ["エラー1", "エラー2", ...]
        }
    """
    result = {
        "spray_date": None,
        "spray_datetime": None,
        "gps": None,
        "pesticide_name": None,
        "confidence": None,
        "errors": []
    }

    # EXIF解析
    exif_result = extract_exif(image_path)

    if exif_result.get("error"):
        result["errors"].append(f"EXIF: {exif_result['error']}")
    else:
        if exif_result.get("datetime"):
            result["spray_datetime"] = exif_result["datetime"]
            # 日付部分のみも抽出
            result["spray_date"] = exif_result["datetime"][:10]

        if exif_result.get("gps"):
            result["gps"] = exif_result["gps"]

    # Vision API で農薬名認識
    vision_result = recognize_pesticide_name(image_path)

    if vision_result.get("error"):
        result["errors"].append(f"Vision: {vision_result['error']}")
    else:
        result["pesticide_name"] = vision_result.get("pesticide_name")
        result["confidence"] = vision_result.get("confidence")

    return result


# =============================================================================
# テスト用
# =============================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python image_analyzer.py <image_path>")
        print("\nテスト（EXIF のみ）:")
        print("  python image_analyzer.py test.jpg --exif-only")
        sys.exit(1)

    image_path = sys.argv[1]
    exif_only = "--exif-only" in sys.argv

    print(f"解析対象: {image_path}")
    print("-" * 40)

    if exif_only:
        result = extract_exif(image_path)
        print("EXIF解析結果:")
        print(f"  撮影日時: {result.get('datetime')}")
        print(f"  GPS: {result.get('gps')}")
        if result.get('error'):
            print(f"  エラー: {result['error']}")
    else:
        result = analyze_image(image_path)
        print("総合解析結果:")
        print(f"  散布日: {result.get('spray_date')}")
        print(f"  GPS: {result.get('gps')}")
        print(f"  農薬名: {result.get('pesticide_name')}")
        print(f"  確信度: {result.get('confidence')}")
        if result.get('errors'):
            print(f"  エラー: {result['errors']}")
