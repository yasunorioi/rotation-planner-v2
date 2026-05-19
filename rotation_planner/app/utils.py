"""
ユーティリティモジュール
データ読み込み・変換・結果生成
"""

import pandas as pd
import re
from typing import Dict, List, Tuple, Optional, Set
from dataclasses import dataclass, field


# =============================================================================
# 定数
# =============================================================================

UNKNOWN_MARKER = "UNKNOWN"

# 列名マッピング（期待列名: 代替列名リスト）
COLUMN_ALIASES = {
    'ほ場ID': ['field', 'ほ場名', 'field_id', 'id'],
    '地区': ['region', 'district', '地域'],
    'ほ場名': ['field', 'name', '名前', '名称'],
    'area': ['面積', 'area_ha', '面積(ha)', '面積(a)'],
    'beet_forbidden': ['禁止', 'てんさい禁止'],
}


# =============================================================================
# データクラス
# =============================================================================

@dataclass
class Field:
    """ほ場データ"""
    field_id: str
    district: str
    name: str
    area_ha: float
    history: Dict[str, str] = field(default_factory=dict)  # year -> crop
    has_unknown: bool = False
    beet_forbidden: bool = False  # 馬鈴薯・てんさい禁止


# =============================================================================
# ユーティリティ関数
# =============================================================================

def parse_year_columns(columns: List[str]) -> List[str]:
    """R数字 形式の年列を抽出"""
    year_pattern = re.compile(r'^R\d+$')
    return [c for c in columns if year_pattern.match(c)]


def generate_future_years(past_years: List[str], n_years: int) -> List[str]:
    """将来の年列を生成"""
    if not past_years:
        return [f"R{i}" for i in range(9, 9 + n_years)]

    # 最後の年から続きを生成
    last_year = max(int(y[1:]) for y in past_years)
    return [f"R{last_year + i + 1}" for i in range(n_years)]


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """列名を正規化する"""
    renamed = {}
    for expected, aliases in COLUMN_ALIASES.items():
        if expected not in df.columns:
            for alias in aliases:
                if alias in df.columns:
                    renamed[alias] = expected
                    break
    if renamed:
        df = df.rename(columns=renamed)
    return df


def infer_crop_for_year(field: 'Field', year: str, crops: List[str],
                        forbidden_transitions: Set[Tuple[str, str]]) -> Optional[str]:
    """その年の作物を推論"""
    excluded = set()
    years = sorted(field.history.keys(), key=lambda y: int(y[1:]))
    if year not in years:
        return None
    year_idx = years.index(year)

    # 1. 連作禁止から逆算（前後の作物と同じものは除外）
    if year_idx > 0:
        prev_crop = field.history.get(years[year_idx - 1], "").replace("*", "")
        if prev_crop and prev_crop != UNKNOWN_MARKER:
            excluded.add(prev_crop)
    if year_idx < len(years) - 1:
        next_crop = field.history.get(years[year_idx + 1], "").replace("*", "")
        if next_crop and next_crop != UNKNOWN_MARKER:
            excluded.add(next_crop)

    # 2. 禁止遷移から逆算
    if year_idx < len(years) - 1:
        next_crop = field.history.get(years[year_idx + 1], "").replace("*", "")
        if next_crop and next_crop != UNKNOWN_MARKER:
            for from_c, to_c in forbidden_transitions:
                if to_c == next_crop:
                    excluded.add(from_c)
    if year_idx > 0:
        prev_crop = field.history.get(years[year_idx - 1], "").replace("*", "")
        if prev_crop and prev_crop != UNKNOWN_MARKER:
            for from_c, to_c in forbidden_transitions:
                if from_c == prev_crop:
                    excluded.add(to_c)

    # 3. 間隔制約から推測（前後4年以内にてんさい・ばれいしょがあれば除外）
    for i, y in enumerate(years):
        if abs(i - year_idx) <= 4 and i != year_idx:
            c = field.history.get(y, "").replace("*", "")
            if c == "てんさい":
                excluded.add("てんさい")
            if c == "ばれいしょ":
                excluded.add("ばれいしょ")

    # 4. beet_forbidden の場合
    if field.beet_forbidden:
        excluded.add("てんさい")
        excluded.add("ばれいしょ")

    # 5. 候補を決定
    candidates = [c for c in crops if c not in excluded]
    if not candidates:
        return None

    # 6. 最も使用頻度の低い作物を選択（面積バランス考慮）
    return candidates[0]


def infer_unknown_crops(fields: List['Field'], crops: List[str],
                        forbidden_transitions: Set[Tuple[str, str]]) -> List['Field']:
    """空欄を推論で埋める"""
    for field in fields:
        for year, crop in list(field.history.items()):
            if crop == UNKNOWN_MARKER:
                inferred = infer_crop_for_year(field, year, crops, forbidden_transitions)
                if inferred:
                    field.history[year] = inferred + "*"  # 推論マーク
                    field.has_unknown = False  # 推論で埋まったのでフラグ更新
    return fields


def load_csv(file_path: str, area_unit: str) -> Tuple[List[Field], List[str], str]:
    """CSVを読み込んでFieldリストを返す"""
    try:
        df = pd.read_csv(file_path, encoding='utf-8')
    except UnicodeDecodeError:
        df = pd.read_csv(file_path, encoding='shift_jis')

    # 列名の正規化（空白除去）
    df.columns = df.columns.str.strip()

    # 列名エイリアスの適用
    df = normalize_columns(df)

    # ほ場IDの自動生成（列がない場合）
    if 'ほ場ID' not in df.columns:
        df['ほ場ID'] = [f'F{i+1:03d}' for i in range(len(df))]

    # 地区・ほ場名のフォールバック
    if '地区' not in df.columns:
        df['地区'] = ''
    if 'ほ場名' not in df.columns:
        df['ほ場名'] = df['ほ場ID']

    # 必須列のチェック（area のみ）
    if 'area' not in df.columns:
        return [], [], "エラー: 必須列 'area' がありません"

    # 年列の抽出
    year_cols = parse_year_columns(df.columns.tolist())
    if not year_cols:
        return [], [], "エラー: 年列（R数字形式）が見つかりません"

    # ソート
    year_cols = sorted(year_cols, key=lambda x: int(x[1:]))

    fields = []
    for _, row in df.iterrows():
        field_id = str(row['ほ場ID']).strip()
        district = str(row.get('地区', '')).strip() if pd.notna(row.get('地区', '')) else ''
        name = str(row.get('ほ場名', '')).strip() if pd.notna(row.get('ほ場名', '')) else ''

        # 面積変換
        area = row['area']
        if pd.isna(area) or area == '':
            area_ha = 0.0
        else:
            area_val = float(area)
            area_ha = area_val / 100 if area_unit.startswith('a') else area_val

        # 作付履歴
        history = {}
        has_unknown = False
        for y in year_cols:
            crop = row.get(y, '')
            if pd.isna(crop) or str(crop).strip() == '':
                history[y] = UNKNOWN_MARKER
                has_unknown = True
            else:
                history[y] = str(crop).strip()

        # beet_forbidden 列を読み込む（列がなければ False）
        beet_forbidden = False
        if 'beet_forbidden' in df.columns:
            val = row.get('beet_forbidden', 0)
            beet_forbidden = bool(int(val)) if pd.notna(val) and str(val).strip() != '' else False

        fields.append(Field(
            field_id=field_id,
            district=district,
            name=name,
            area_ha=area_ha,
            history=history,
            has_unknown=has_unknown,
            beet_forbidden=beet_forbidden
        ))

    return fields, year_cols, ""


def generate_result_tables(fields: List[Field], past_years: List[str],
                          future_years: List[str], plan: Dict, crops: List[str]):
    """結果テーブルを生成"""
    all_years = past_years + future_years

    # 今年（将来年の最初）を特定
    current_year = future_years[0] if future_years else None

    # 列名マッピング（今年に📍マーカーを付ける）
    def year_col_name(year):
        if year == current_year:
            return f"📍{year}"
        return year

    # 1. ほ場×年の表
    rows = []
    for i, f in enumerate(fields):
        row = {
            "ほ場ID": f.field_id,
            "地区": f.district,
            "ほ場名": f.name,
            "面積(ha)": f"{f.area_ha:.2f}",
            "禁止": "🚫" if f.beet_forbidden else ""
        }
        for year in all_years:
            col_name = year_col_name(year)
            if year in past_years:
                row[col_name] = f.history.get(year, "")
                if row[col_name] == UNKNOWN_MARKER:
                    row[col_name] = "(不明)"
            else:
                row[col_name] = plan.get((i, year), "")
        rows.append(row)

    field_df = pd.DataFrame(rows)

    # 2. 年別面積合計表
    summary_rows = []
    for year in all_years:
        row_year = year_col_name(year)
        row = {"年": row_year}
        for crop in crops:
            total_ha = 0.0
            for i, f in enumerate(fields):
                if year in past_years:
                    c = f.history.get(year, UNKNOWN_MARKER)
                else:
                    c = plan.get((i, year), "")
                if c == crop:
                    total_ha += f.area_ha
            row[crop] = f"{total_ha:.2f}" if total_ha > 0 else ""
        summary_rows.append(row)

    summary_df = pd.DataFrame(summary_rows)

    return field_df, summary_df


def generate_csv_content(field_df: pd.DataFrame) -> str:
    """CSVコンテンツを生成"""
    return field_df.to_csv(index=False)
