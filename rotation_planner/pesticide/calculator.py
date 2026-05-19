"""
農薬計算ロジックモジュール

農薬必要量の計算、単位変換、作物名正規化などのビジネスロジックを提供。
"""

import pandas as pd
import re
from typing import Dict, List, Tuple, Optional, Any

# =============================================================================
# 定数
# =============================================================================

# 単位変換係数（基準単位への変換）
UNIT_CONVERSION = {
    'L': 1000,      # L -> mL
    'l': 1000,
    'mL': 1,        # mL (基準)
    'ml': 1,
    'kg': 1000,     # kg -> g
    'g': 1,         # g (基準)
}

# 散布基準: 10a あたり 100L
SPRAY_VOLUME_PER_10A = 100  # L

# 作物名の正規化マッピング
CROP_NORMALIZE = {
    "てんさい": "てんさい",
    "ビート": "てんさい",
    "甜菜": "てんさい",
    "テンサイ": "てんさい",
    "大豆": "大豆",
    "春小麦": "春小麦",
    "秋小麦": "秋小麦",
    "デントコーン": "デントコーン",
    "コーン": "デントコーン",
    "WCS": "WCS",
    "馬鈴薯": "馬鈴薯",
    "ばれいしょ": "馬鈴薯",
}


# =============================================================================
# 単位変換
# =============================================================================

def convert_to_base_unit(amount: float, unit: str) -> float:
    """指定単位から基準単位（mL or g）に変換"""
    conversion = UNIT_CONVERSION.get(unit, 1)
    return amount * conversion


def convert_from_base_unit(amount_base: float, target_unit: str) -> float:
    """基準単位から指定単位に変換"""
    conversion = UNIT_CONVERSION.get(target_unit, 1)
    return amount_base / conversion


# =============================================================================
# 作物名正規化
# =============================================================================

def normalize_crop(crop: str) -> str:
    """作物名を正規化"""
    if pd.isna(crop) or str(crop).strip() == '':
        return ''
    crop_str = str(crop).strip()
    return CROP_NORMALIZE.get(crop_str, crop_str)


# =============================================================================
# データ読み込み
# =============================================================================

def load_rotation_plan(csv_path: str) -> Tuple[pd.DataFrame, List[str], str]:
    """輪作計画CSVを読み込み、ほ場情報と年列を抽出"""
    try:
        df = pd.read_csv(csv_path, encoding='utf-8-sig')
    except (UnicodeDecodeError, LookupError) as e:
        df = pd.read_csv(csv_path, encoding='utf-8')

    # 年列を特定（R + 数字、または 📍R + 数字）
    year_pattern = re.compile(r'^📍?R\d+$')
    year_cols = [c for c in df.columns if year_pattern.match(c)]

    if not year_cols:
        return None, [], "エラー: 年列（R5, R6, ...）が見つかりません"

    # 📍を除去して正規化
    year_cols_clean = [c.replace('📍', '') for c in year_cols]

    return df, year_cols, None


def load_inventory_csv(csv_path: str) -> Tuple[Dict[str, Tuple[float, str]], str]:
    """
    在庫CSVを読み込み

    形式: 農薬名,在庫量,単位

    Returns:
        inventory_dict: {農薬名: (在庫量(基準単位), 元の単位)}
        message: 警告メッセージ（エラー時）
    """
    inventory = {}
    warnings = []

    try:
        try:
            df = pd.read_csv(csv_path, encoding='utf-8-sig')
        except (UnicodeDecodeError, LookupError) as e:
            df = pd.read_csv(csv_path, encoding='utf-8')

        # 列名を正規化
        df.columns = df.columns.str.strip()

        # 必要な列をチェック
        required_cols = ['農薬名', '在庫量', '単位']
        missing_cols = [c for c in required_cols if c not in df.columns]
        if missing_cols:
            return {}, f"警告: 在庫CSVに必要な列がありません: {', '.join(missing_cols)}"

        for _, row in df.iterrows():
            name = str(row['農薬名']).strip()
            if not name or name == 'nan':
                continue

            try:
                amount = float(row['在庫量'])
            except (ValueError, TypeError):
                warnings.append(f"在庫量が不正: {name}")
                continue

            unit = str(row['単位']).strip()

            # 基準単位（mL または g）に変換
            conversion = UNIT_CONVERSION.get(unit, 1)
            amount_base = amount * conversion

            inventory[name] = (amount_base, unit)

    except Exception as e:
        return {}, f"警告: 在庫CSVの読み込みに失敗しました: {str(e)}"

    warning_msg = ""
    if warnings:
        warning_msg = "在庫CSV警告: " + "; ".join(warnings[:3])
        if len(warnings) > 3:
            warning_msg += f" 他{len(warnings)-3}件"

    return inventory, warning_msg


# =============================================================================
# 農薬必要量計算
# =============================================================================

def calculate_pesticide_requirements(
    rotation_df: pd.DataFrame,
    year_cols: List[str],
    target_year: str,
    master_df: pd.DataFrame,
    area_unit: str = 'a',
    inventory: Dict[str, Tuple[float, str]] = None
) -> Tuple[pd.DataFrame, pd.DataFrame, str]:
    """
    指定年の農薬必要量を計算

    Args:
        rotation_df: 輪作計画DataFrame
        year_cols: 年列リスト
        target_year: 対象年
        master_df: 防除マスタDataFrame
        area_unit: 面積単位（'a' or 'ha'）
        inventory: 在庫データ {農薬名: (在庫量(基準単位), 元の単位)}

    Returns:
        summary_df: 農薬別の必要量サマリ
        detail_df: 月別・農薬別の詳細
        message: 処理メッセージ
    """
    has_inventory = inventory is not None and len(inventory) > 0

    # 対象年の列を特定
    target_col = None
    for col in rotation_df.columns:
        if col.replace('📍', '') == target_year or col == target_year:
            target_col = col
            break

    if target_col is None:
        return None, None, f"エラー: {target_year} が見つかりません"

    # 面積列を特定
    area_col = None
    for col in ['面積(ha)', 'area', '面積']:
        if col in rotation_df.columns:
            area_col = col
            break

    if area_col is None:
        return None, None, "エラー: 面積列が見つかりません"

    # 作物ごとの面積を集計
    crop_areas = {}  # crop -> total_ha

    for _, row in rotation_df.iterrows():
        crop = normalize_crop(row[target_col])
        if not crop:
            continue

        area = row[area_col]
        if pd.isna(area):
            continue

        # 面積を数値化
        area_str = str(area).replace('ha', '').replace('a', '').strip()
        try:
            area_val = float(area_str)
        except (ValueError, TypeError) as e:
            continue

        # haに変換
        if area_unit == 'a':
            area_ha = area_val / 100
        else:
            area_ha = area_val

        if crop not in crop_areas:
            crop_areas[crop] = 0
        crop_areas[crop] += area_ha

    if not crop_areas:
        return None, None, "エラー: 作付データがありません"

    # 農薬必要量を計算
    pesticide_totals = {}  # pesticide_name -> {amount, unit, crops, targets}
    monthly_details = []  # [{month, crop, target, pesticide, amount, unit}, ...]

    for crop, area_ha in crop_areas.items():
        # マスタから該当作物の農薬を取得
        crop_master = master_df[master_df['crop'] == crop]

        if crop_master.empty:
            continue

        area_10a = area_ha * 10  # haを10a単位に変換

        for _, prow in crop_master.iterrows():
            pesticide = prow['pesticide_name']
            dilution = prow['dilution_rate']
            amount_per_10a = prow['amount_per_10a']
            unit = prow['unit']
            month = prow['month']
            target = prow['target']

            # 必要量を計算
            if pd.notna(amount_per_10a) and str(amount_per_10a).strip() != '':
                # 直接指定（mL/10a, g/10a など）
                try:
                    # 複数値の場合は最初の値を使用（例: 400+100）
                    amount_str = str(amount_per_10a).split('+')[0].split('/')[0].split('〜')[0]
                    amount = float(amount_str) * area_10a
                    final_unit = str(unit) if pd.notna(unit) else 'mL'
                except (ValueError, TypeError, ZeroDivisionError) as e:
                    continue
            elif pd.notna(dilution) and str(dilution).strip() != '':
                # 希釈倍率指定 → 100L/10a 基準で計算
                try:
                    dilution_str = str(dilution).split('/')[0].split('〜')[0].replace(',', '')
                    dilution_rate = float(dilution_str)
                    # 100L/10a ÷ 希釈倍率 × 面積(10a)
                    amount = (SPRAY_VOLUME_PER_10A / dilution_rate) * area_10a * 1000  # mL
                    final_unit = 'mL'
                except (ValueError, TypeError, ZeroDivisionError) as e:
                    continue
            else:
                continue

            # 集計
            if pesticide not in pesticide_totals:
                pesticide_totals[pesticide] = {
                    'amount': 0,
                    'unit': final_unit,
                    'crops': set(),
                    'targets': set()
                }
            pesticide_totals[pesticide]['amount'] += amount
            pesticide_totals[pesticide]['crops'].add(crop)
            if pd.notna(target):
                pesticide_totals[pesticide]['targets'].add(str(target))

            # 月別詳細
            monthly_details.append({
                'month': int(month) if pd.notna(month) else 0,
                'crop': crop,
                'target': target if pd.notna(target) else '',
                'pesticide': pesticide,
                'amount': amount,
                'unit': final_unit,
                'area_ha': area_ha
            })

    if not pesticide_totals:
        return None, None, f"警告: {target_year}の作物に対応する農薬データがありません"

    # サマリDataFrame作成
    summary_rows = []
    for pesticide, data in sorted(pesticide_totals.items()):
        amount = data['amount']  # 基準単位（mL or g）
        unit = data['unit']

        # 単位変換（1000mL以上はL、1000g以上はkg）
        if unit == 'mL' and amount >= 1000:
            amount_disp = amount / 1000
            unit_disp = 'L'
        elif unit == 'g' and amount >= 1000:
            amount_disp = amount / 1000
            unit_disp = 'kg'
        else:
            amount_disp = amount
            unit_disp = unit

        row = {
            '農薬名': pesticide,
            '必要量': f"{amount_disp:.2f}",
        }

        # 在庫・発注量の計算（在庫データがある場合のみ）
        if has_inventory:
            inv_amount_base = 0.0
            inv_unit = unit_disp

            if pesticide in inventory:
                inv_amount_base, inv_unit_orig = inventory[pesticide]
                # 表示用単位に変換
                if unit_disp == 'L':
                    inv_amount_disp = inv_amount_base / 1000  # mL -> L
                elif unit_disp == 'kg':
                    inv_amount_disp = inv_amount_base / 1000  # g -> kg
                else:
                    inv_amount_disp = inv_amount_base
            else:
                inv_amount_disp = 0.0

            # 発注量 = max(0, 必要量 - 在庫)
            order_amount = max(0, amount_disp - inv_amount_disp)

            row['在庫量'] = f"{inv_amount_disp:.2f}"
            row['発注量'] = f"{order_amount:.2f}"

        row['単位'] = unit_disp
        row['対象作物'] = ', '.join(sorted(data['crops']))
        row['対象病害虫'] = ', '.join(sorted(data['targets']))[:50]

        summary_rows.append(row)

    summary_df = pd.DataFrame(summary_rows)

    # 月別詳細DataFrame作成
    detail_df = pd.DataFrame(monthly_details)
    if not detail_df.empty:
        detail_df = detail_df.sort_values(['month', 'crop', 'pesticide'])

        # 表示用に整形
        detail_df['amount_disp'] = detail_df.apply(
            lambda r: f"{r['amount']/1000:.2f}L" if r['unit'] == 'mL' and r['amount'] >= 1000
                     else f"{r['amount']:.1f}{r['unit']}", axis=1
        )
        detail_df = detail_df[['month', 'crop', 'target', 'pesticide', 'amount_disp', 'area_ha']]
        detail_df.columns = ['月', '作物', '対象', '農薬名', '必要量', '面積(ha)']

    # メッセージ
    message = f"✅ {target_year}の農薬発注リスト作成完了\n"
    message += f"・対象作物: {', '.join(f'{c}({a:.2f}ha)' for c, a in sorted(crop_areas.items()))}\n"
    message += f"・農薬品目数: {len(summary_df)}\n"

    return summary_df, detail_df, message
