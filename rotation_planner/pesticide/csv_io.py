"""
発注CSVのインポート/エクスポート

過去年度の発注CSVを翌年度に再利用するための機能。
"""

import pandas as pd
import io
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime


def export_order_csv(
    summary_data: List[Dict[str, Any]],
    year: str,
    output_path: Optional[str] = None
) -> Tuple[str, bytes]:
    """
    発注リストをCSVエクスポート（翌年インポート用）

    Args:
        summary_data: 発注サマリデータ [{農薬名, 必要量, 単位, 作物}, ...]
        year: 年度 (R9など)
        output_path: 出力パス (Noneの場合はbytesのみ返却)

    Returns:
        (filename, csv_bytes)
    """
    df = pd.DataFrame(summary_data)

    # カラム順序を整理
    columns = ['農薬名', '必要量', '単位', '対象作物']
    for col in columns:
        if col not in df.columns:
            # 代替カラム名を探す
            alt_names = {
                '農薬名': ['pesticide_name', 'name'],
                '必要量': ['amount', 'total_amount', '量'],
                '単位': ['unit'],
                '対象作物': ['crops', 'crop', '作物'],
            }
            for alt in alt_names.get(col, []):
                if alt in df.columns:
                    df[col] = df[alt]
                    break
            else:
                df[col] = ''

    df = df[columns]

    # CSV生成
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False, encoding='utf-8')
    csv_bytes = csv_buffer.getvalue().encode('utf-8-sig')

    filename = f"pesticide_order_{year}.csv"

    if output_path:
        Path(output_path).write_bytes(csv_bytes)

    return filename, csv_bytes


def import_order_csv(
    csv_file,
    crop_areas: Optional[Dict[str, float]] = None
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    過去発注CSVをインポート

    Args:
        csv_file: CSVファイル (ファイルパス or ファイルオブジェクト)
        crop_areas: 今年度の作物×面積 (指定時は比率で再計算)

    Returns:
        (items, warnings)
        items: [{農薬名, 必要量, 単位, 対象作物}, ...]
        warnings: 警告メッセージリスト
    """
    warnings = []

    # CSV読み込み
    try:
        if hasattr(csv_file, 'name'):
            # Gradioのファイルオブジェクト
            df = pd.read_csv(csv_file.name, encoding='utf-8-sig')
        elif isinstance(csv_file, (str, Path)):
            df = pd.read_csv(csv_file, encoding='utf-8-sig')
        else:
            df = pd.read_csv(io.BytesIO(csv_file), encoding='utf-8-sig')
    except Exception as e:
        try:
            if hasattr(csv_file, 'name'):
                df = pd.read_csv(csv_file.name, encoding='utf-8')
            else:
                df = pd.read_csv(csv_file, encoding='utf-8')
        except Exception as e2:
            return [], [f"CSV読み込みエラー: {e2}"]

    # カラム名の正規化
    column_map = {
        'pesticide_name': '農薬名',
        'name': '農薬名',
        'amount': '必要量',
        'total_amount': '必要量',
        '量': '必要量',
        'unit': '単位',
        'crops': '対象作物',
        'crop': '対象作物',
        '作物': '対象作物',
    }
    df = df.rename(columns=column_map)

    # 必須カラムチェック
    required = ['農薬名']
    missing = [c for c in required if c not in df.columns]
    if missing:
        return [], [f"必須カラムがありません: {missing}"]

    # データ変換
    items = []
    for _, row in df.iterrows():
        item = {
            '農薬名': str(row.get('農薬名', '')),
            '必要量': float(row.get('必要量', 0)) if pd.notna(row.get('必要量')) else 0,
            '単位': str(row.get('単位', '')) if pd.notna(row.get('単位')) else '',
            '対象作物': str(row.get('対象作物', '')) if pd.notna(row.get('対象作物')) else '',
            '編集可': True,  # インポートデータは編集可能
        }
        if item['農薬名']:
            items.append(item)

    if not items:
        warnings.append("有効なデータがありませんでした")

    # 今年度面積での再計算（オプション）
    # Note: 去年の面積が不明なため、単純な比率計算は困難
    # → そのまま読み込み、ユーザーが手動調整する想定
    if crop_areas:
        warnings.append("面積データあり: 必要に応じて手動で調整してください")

    return items, warnings


def merge_with_calculated(
    imported_items: List[Dict[str, Any]],
    calculated_items: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    インポートデータと計算データをマージ

    Args:
        imported_items: インポートした発注リスト
        calculated_items: 今年度の計算結果

    Returns:
        マージされたリスト（インポートデータ優先、不足分は計算から補完）
    """
    result = []
    imported_names = {item['農薬名'] for item in imported_items}

    # インポートデータを優先
    for item in imported_items:
        item['ソース'] = 'インポート'
        result.append(item)

    # 計算データで補完（インポートにないもの）
    for item in calculated_items:
        name = item.get('農薬名') or item.get('pesticide_name', '')
        if name and name not in imported_names:
            result.append({
                '農薬名': name,
                '必要量': item.get('必要量') or item.get('amount', 0),
                '単位': item.get('単位') or item.get('unit', ''),
                '対象作物': item.get('対象作物') or item.get('crops', ''),
                '編集可': True,
                'ソース': '計算',
            })

    return result
