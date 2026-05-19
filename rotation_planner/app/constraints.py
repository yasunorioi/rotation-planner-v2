"""
制約設定モジュール
作物の制約定義・パース・テーブル管理
"""

import pandas as pd
from typing import Dict, List, Tuple, Optional, Set
from dataclasses import dataclass, field


# =============================================================================
# 定数・デフォルト値
# =============================================================================

# ハードコードのフォールバック値（DB接続できない場合に使用）
# FAMIC表記に準拠
_FALLBACK_CROPS = [
    "小麦(春播)", "小麦(秋播)", "だいず", "デントコーン", "WCS",
    "てんさい", "ばれいしょ", "キャベツ", "にんじん", "だいこん"
]


def get_default_crops(user_id: int = None) -> List[str]:
    """
    作物リストを取得する。

    Args:
        user_id: ユーザーID（指定時はユーザーの選択作物のみ返す）

    Returns:
        作物名のリスト

    優先順位:
        1. user_idがあればユーザーの選択作物（user_crops）のみ
        2. user_idがなければ全マスタ（crop_master）
        3. ハードコードのフォールバック
    """
    try:
        from rotation_planner.common import CropMasterRepository, UserCropRepository
    except ImportError:
        return _FALLBACK_CROPS

    # 1. ユーザーIDがあれば、ユーザーの選択作物のみを返す
    if user_id:
        try:
            crops = UserCropRepository.get_user_crops(user_id)
            # user_cropsが空でも全マスタにフォールバックしない
            # ユーザーは自分の作物だけ見たい
            return [c.get("custom_name") or c.get("name", "") for c in crops if c.get("custom_name") or c.get("name")]
        except Exception:
            return []  # エラー時は空リスト

    # 2. user_idがない場合のみ全マスタから取得
    try:
        crops = CropMasterRepository.get_all(active_only=True)
        if crops:
            return [c.get("name", "") for c in crops if c.get("name")]
    except Exception:
        pass

    # 3. フォールバック
    return _FALLBACK_CROPS


# 後方互換性のため、デフォルト値も維持（モジュール読み込み時に評価）
DEFAULT_CROPS = get_default_crops()

# FAMIC表記に準拠
DEFAULT_CONSTRAINTS = {
    "小麦(春播)": {"min_ha": None, "cap_ha": 10, "min_gap_years": 0, "min_fields": 0, "max_fields": None},
    "小麦(秋播)": {"min_ha": None, "cap_ha": 10, "min_gap_years": 0, "min_fields": 0, "max_fields": None},
    "だいず":     {"min_ha": None, "cap_ha": 12, "min_gap_years": 0, "min_fields": 0, "max_fields": None},
    "デントコーン": {"min_ha": None, "cap_ha": 8, "min_gap_years": 0, "min_fields": 0, "max_fields": None},
    "WCS":        {"min_ha": None, "cap_ha": 4, "min_gap_years": 0, "min_fields": 0, "max_fields": None},
    "てんさい":   {"min_ha": None, "cap_ha": None, "min_gap_years": 4, "min_fields": 0, "max_fields": 2},
    "ばれいしょ": {"min_ha": None, "cap_ha": None, "min_gap_years": 4, "min_fields": 0, "max_fields": None},
    "キャベツ":   {"min_ha": None, "cap_ha": 10, "min_gap_years": 0, "min_fields": 0, "max_fields": None},
    "にんじん":   {"min_ha": None, "cap_ha": 10, "min_gap_years": 0, "min_fields": 0, "max_fields": None},
    "だいこん":   {"min_ha": None, "cap_ha": 10, "min_gap_years": 0, "min_fields": 0, "max_fields": None},
}

# 固定の禁止遷移（FAMIC表記）
FIXED_FORBIDDEN_TRANSITIONS = [
    ("てんさい", "小麦(秋播)"),  # 作期重複
    ("小麦(春播)", "小麦(秋播)"),    # 病害対策
]

# デフォルトの優先遷移（FAMIC表記）
DEFAULT_PREFERRED_TRANSITIONS = "てんさい->だいず:10, てんさい->小麦(春播):5, デントコーン->小麦(秋播):8"

# 主作物（面積変動を抑えたい）（FAMIC表記）
DEFAULT_MAIN_CROPS = "小麦(春播), 小麦(秋播), だいず"


# =============================================================================
# データクラス
# =============================================================================

@dataclass
class Constraints:
    """制約設定"""
    crop_mins: Dict[str, Optional[float]] = field(default_factory=dict)  # min_ha
    crop_caps: Dict[str, Optional[float]] = field(default_factory=dict)  # cap_ha
    min_gap_years: Dict[str, int] = field(default_factory=dict)
    min_fields: Dict[str, int] = field(default_factory=dict)
    max_fields: Dict[str, Optional[int]] = field(default_factory=dict)
    forbidden_transitions: Set[Tuple[str, str]] = field(default_factory=set)
    preferred_transitions: Dict[Tuple[str, str], float] = field(default_factory=dict)
    main_crops: List[str] = field(default_factory=list)
    unknown_mode: str = "ignore"  # "ignore" or "safe"
    # PRO: 隣接筆の同一科制約
    adjacent_family_enabled: bool = False
    adjacency_pairs: List[Tuple[int, int]] = field(default_factory=list)  # field index pairs
    crop_family_map: Dict[str, str] = field(default_factory=dict)  # crop_name -> family


# =============================================================================
# 制約テーブル関数
# =============================================================================

def build_constraints_table(crops: List[str]) -> pd.DataFrame:
    """作物リストから制約テーブルを構築"""
    rows = []
    for crop in crops:
        if crop in DEFAULT_CONSTRAINTS:
            c = DEFAULT_CONSTRAINTS[crop]
        else:
            c = {"min_ha": None, "cap_ha": 10, "min_gap_years": 0, "min_fields": 0, "max_fields": None}

        rows.append({
            "crop": crop,
            "min_ha": c.get("min_ha", "") if c.get("min_ha") is not None else "",
            "cap_ha": c["cap_ha"] if c["cap_ha"] is not None else "",
            "min_gap_years": c["min_gap_years"],
            "min_fields": c["min_fields"],
            "max_fields": c["max_fields"] if c["max_fields"] is not None else ""
        })

    return pd.DataFrame(rows)


def load_constraints_csv(file_path: str) -> pd.DataFrame:
    """制約CSVを読み込んでDataFrameに変換"""
    try:
        df = pd.read_csv(file_path, encoding='utf-8-sig')
    except Exception:
        try:
            df = pd.read_csv(file_path, encoding='utf-8')
        except Exception:
            df = pd.read_csv(file_path, encoding='shift_jis')

    # 列名の正規化（空白除去）
    df.columns = df.columns.str.strip()

    # 必要な列が存在するか確認
    required_cols = ['crop']
    for col in required_cols:
        if col not in df.columns:
            return pd.DataFrame()

    return df


def parse_constraints_table(df: pd.DataFrame) -> Tuple[Dict, Dict, Dict, Dict, Dict]:
    """制約テーブルをパース"""
    crop_mins = {}  # min_ha
    crop_caps = {}  # cap_ha
    min_gap = {}
    min_f = {}
    max_f = {}

    for _, row in df.iterrows():
        crop = str(row['crop']).strip()
        if not crop:
            continue

        # min_ha (0または空欄は無制限=下限なし)
        min_ha = row.get('min_ha', '')
        if pd.notna(min_ha) and str(min_ha).strip() != '':
            try:
                val = float(min_ha)
                crop_mins[crop] = val if val > 0 else None
            except (ValueError, TypeError):
                crop_mins[crop] = None
        else:
            crop_mins[crop] = None

        # cap_ha (0または空欄は無制限)
        cap = row.get('cap_ha', '')
        if pd.notna(cap) and str(cap).strip() != '':
            try:
                val = float(cap)
                crop_caps[crop] = val if val > 0 else None
            except (ValueError, TypeError):
                crop_caps[crop] = None
        else:
            crop_caps[crop] = None

        # min_gap_years
        gap = row.get('min_gap_years', 0)
        try:
            min_gap[crop] = int(gap) if pd.notna(gap) and str(gap).strip() != '' else 0
        except (ValueError, TypeError):
            min_gap[crop] = 0

        # min_fields
        minf = row.get('min_fields', 0)
        try:
            min_f[crop] = int(minf) if pd.notna(minf) and str(minf).strip() != '' else 0
        except (ValueError, TypeError):
            min_f[crop] = 0

        # max_fields (0は無制限として扱う)
        maxf = row.get('max_fields', '')
        if pd.notna(maxf) and str(maxf).strip() != '':
            try:
                val = int(maxf)
                max_f[crop] = val if val > 0 else None
            except (ValueError, TypeError):
                max_f[crop] = None
        else:
            max_f[crop] = None

    return crop_mins, crop_caps, min_gap, min_f, max_f


def parse_forbidden_transitions(text: str) -> Set[Tuple[str, str]]:
    """追加禁止遷移をパース (例: "秋小麦->春小麦, 大豆->てんさい")"""
    transitions = set()
    if not text.strip():
        return transitions

    for item in text.split(','):
        item = item.strip()
        if '->' in item:
            parts = item.split('->')
            if len(parts) == 2:
                from_crop = parts[0].strip()
                to_crop = parts[1].strip()
                if from_crop and to_crop:
                    transitions.add((from_crop, to_crop))

    return transitions


def parse_preferred_transitions(text: str) -> Dict[Tuple[str, str], float]:
    """優先遷移をパース (例: "てんさい->大豆:10, デントコーン->秋小麦:8")"""
    transitions = {}
    if not text.strip():
        return transitions

    for item in text.split(','):
        item = item.strip()
        if '->' in item and ':' in item:
            try:
                trans_part, weight_part = item.rsplit(':', 1)
                parts = trans_part.split('->')
                if len(parts) == 2:
                    from_crop = parts[0].strip()
                    to_crop = parts[1].strip()
                    weight = float(weight_part.strip())
                    if from_crop and to_crop:
                        transitions[(from_crop, to_crop)] = weight
            except (ValueError, TypeError):
                continue

    return transitions


def update_constraints_table(crop_text: str, current_table: pd.DataFrame) -> pd.DataFrame:
    """作物マスター変更時に制約テーブルを更新"""
    crops = [c.strip() for c in crop_text.strip().split('\n') if c.strip()]

    if current_table is None or current_table.empty:
        return build_constraints_table(crops)

    # 既存の値を保持
    existing = {}
    for _, row in current_table.iterrows():
        crop = str(row.get('crop', '')).strip()
        if crop:
            existing[crop] = {
                'min_ha': row.get('min_ha', ''),
                'cap_ha': row.get('cap_ha', ''),
                'min_gap_years': row.get('min_gap_years', 0),
                'min_fields': row.get('min_fields', 0),
                'max_fields': row.get('max_fields', '')
            }

    # 新しいテーブルを構築
    rows = []
    for crop in crops:
        if crop in existing:
            rows.append({
                "crop": crop,
                "min_ha": existing[crop]['min_ha'],
                "cap_ha": existing[crop]['cap_ha'],
                "min_gap_years": existing[crop]['min_gap_years'],
                "min_fields": existing[crop]['min_fields'],
                "max_fields": existing[crop]['max_fields']
            })
        elif crop in DEFAULT_CONSTRAINTS:
            c = DEFAULT_CONSTRAINTS[crop]
            rows.append({
                "crop": crop,
                "min_ha": c.get("min_ha", "") if c.get("min_ha") is not None else "",
                "cap_ha": c["cap_ha"] if c["cap_ha"] is not None else "",
                "min_gap_years": c["min_gap_years"],
                "min_fields": c["min_fields"],
                "max_fields": c["max_fields"] if c["max_fields"] is not None else ""
            })
        else:
            rows.append({
                "crop": crop,
                "min_ha": "",
                "cap_ha": 10,
                "min_gap_years": 0,
                "min_fields": 0,
                "max_fields": ""
            })

    return pd.DataFrame(rows)
